import os
import logging
import json
import subprocess
import tempfile
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import google.generativeai as genai
from PIL import Image, ImageWin # Used for image validation/info, though not strictly for printing here
from PyPDF2 import PdfReader
import win32print
import win32ui
import sqlite3
import shutil
from pathlib import Path
import threading
import time

# Remove external module imports for gemini_parser, image_processor, print_manager, logger
# --- Gemini Parser Logic ---
import google.generativeai as genai
import json

def parse_instructions(message_text, num_files):
    prompt = f"""
    You are a helpful assistant for a print bot. The user may send multiple files (images or PDFs) and a message with instructions.
    For each file (1 to {num_files}), extract the following settings from the message:
    - file_index: 1-based index of the file (first file is 1)
    - type: 'image' or 'pdf'
    - copies: integer (default 1)
    - pages: page range (e.g., '1-3', 'all') (for PDFs)
    - orientation: 'portrait' or 'landscape' (default 'portrait')
    - scale_percent: integer (0-100, if user says 'scale 60%' or similar; default 100)
    - scale: 'fit', 'fill', or 'grayscale' (default 'fit')
    - margin_percent: integer percent (e.g., 12 for 12% border; default 0)
    Respond ONLY with a JSON array, one object per file, in order.
    If the message does not mention a file, use defaults for that file.
    Example:
    [
      {{"file_index": 1, "type": "image", "copies": 2, "orientation": "landscape", "scale_percent": 60, "scale": "fit", "margin_percent": 0}},
      {{"file_index": 2, "type": "pdf", "copies": 1, "pages": "1-5", "orientation": "portrait", "scale_percent": 100, "scale": "fit", "margin_percent": 12}}
    ]
    User message: '{message_text}'
    """
    response = genai.GenerativeModel('gemini-2.0-flash').generate_content(prompt)
    response_text = response.text.strip()
    if response_text.startswith("```json") and response_text.endswith("```"):
        response_text = response_text[7:-3].strip()
    settings_list = json.loads(response_text)
    for i, s in enumerate(settings_list):
        s['file_index'] = s.get('file_index', i+1)
        s['type'] = s.get('type', 'image')
        s['copies'] = int(s.get('copies', 1))
        s['pages'] = s.get('pages', 'all')
        s['orientation'] = s.get('orientation', 'portrait')
        s['scale'] = s.get('scale', 'fit')
        s['margin_percent'] = int(s.get('margin_percent', 0))
        s['scale_percent'] = int(s.get('scale_percent', 100)) if 'scale_percent' in s else 100
    return settings_list

# --- Image Processor Logic ---
from PIL import Image, ImageOps

def process_image(file_path, settings, printable_area=None):
    img = Image.open(file_path)
    # Orientation
    if settings.get('orientation') == 'landscape' and img.width < img.height:
        img = img.rotate(90, expand=True)
    # Scale (grayscale)
    if settings.get('scale') == 'grayscale':
        img = img.convert('L')
    # Add border (margin_percent)
    margin_percent = int(settings.get('margin_percent', 0))
    if margin_percent > 0:
        border_px = int(min(img.size) * margin_percent / 100)
        img = ImageOps.expand(img, border=border_px, fill='white')
    # Proportional scaling to scale_percent of printable area (if provided)
    if printable_area and 'scale_percent' in settings:
        scale_percent = max(1, min(int(settings.get('scale_percent', 100)), 100))
        target_w = int(printable_area[0] * scale_percent / 100)
        target_h = int(printable_area[1] * scale_percent / 100)
        img.thumbnail((target_w, target_h), Image.LANCZOS)
    # Always preserve aspect ratio: do not stretch, only fit
    processed_path = file_path.replace('.', '_processed.')
    img.save(processed_path)
    return processed_path

# --- Print Manager Logic ---
import win32print
import win32ui
from PIL import ImageWin

def print_file(file_path, printer_name, settings, dry_run=False):
    if dry_run:
        print(f"[DRY RUN] Would print {file_path} to {printer_name} with settings: {settings}")
        return True
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.jpg', '.jpeg', '.png', '.bmp']:
        try:
            img = Image.open(file_path)
            printer_handle = win32print.OpenPrinter(printer_name)
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)
            hdc.StartDoc(file_path)
            hdc.StartPage()
            printable_area = hdc.GetDeviceCaps(8), hdc.GetDeviceCaps(10)
            # Proportional scaling to scale_percent of printable area
            scale_percent = max(1, min(int(settings.get('scale_percent', 100)), 100))
            target_w = int(printable_area[0] * scale_percent / 100)
            target_h = int(printable_area[1] * scale_percent / 100)
            img.thumbnail((target_w, target_h), Image.LANCZOS)
            # Center image on page
            x = (printable_area[0] - img.width) // 2
            y = (printable_area[1] - img.height) // 2
            dib = ImageWin.Dib(img)
            dib.draw(hdc.GetHandleOutput(), (x, y, x + img.width, y + img.height))
            hdc.EndPage()
            hdc.EndDoc()
            hdc.DeleteDC()
            win32print.ClosePrinter(printer_handle)
            return True
        except Exception as e:
            print(f"Failed to print image: {e}")
            return False
    elif ext == '.pdf':
        print(f"TODO: Print PDF {file_path} with page range {settings.get('pages')} and margin {settings.get('margin_percent')}% (not yet implemented)")
        return False
    else:
        try:
            os.startfile(file_path, f'printto "{printer_name}"')
            return True
        except Exception as e:
            print(f"Failed to print: {e}")
            return False

# --- Logger Logic ---
import datetime

def log_event(msg):
    timestamp = datetime.datetime.now().isoformat()
    print(f"[{timestamp}] {msg}")
    # Optionally, write to a log file
    # with open('printbot.log', 'a') as f:
    #     f.write(f"[{timestamp}] {msg}\n")

# --- Configuration ---
# Replace with your Telegram BotFather token
# It's highly recommended to set this as an environment variable
# TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_TOKEN = 
# Replace with your Gemini API Key
# It's highly recommended to set this as an environment variable
# GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY = 

# Check if environment variables are set
if not TELEGRAM_BOT_TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN environment variable is not set.")
    print("Please set it before running the script (e.g., export TELEGRAM_BOT_TOKEN='YOUR_TOKEN').")
    exit(1)
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY environment variable is not set.")
    print("Please set it before running the script (e.g., export GEMINI_API_KEY='YOUR_KEY').")
    exit(1)

# Configure the Gemini API
genai.configure(api_key=GEMINI_API_KEY)
# Initialize the Gemini model
model = genai.GenerativeModel('gemini-2.0-flash')

# --- Logging Setup ---
# Configure basic logging to show info, warnings, and errors
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Conversation States ---
# Define states for the ConversationHandler to manage multi-step interactions
SELECTING_PRINTER = 0

# --- Global Variables for Conversation State ---
# This dictionary will store temporary data for each user during their conversation
# It's used to pass data between different steps of the conversation
user_data = {}

# --- Helper Functions ---

def get_available_printers():
    """
    Detects and returns a list of available printers on the system.
    This function is OS-dependent and attempts to find printers based on the OS.
    - On Linux/macOS, it uses the `lpstat -p` command (part of CUPS).
    - On Windows, it attempts to use `wmic printer get name` or fallback to PowerShell.
    - If no printers are found or the OS is unsupported, it provides fallback names.
    """
    printers = []
    if os.name == 'posix':  # Linux or macOS
        try:
            result = subprocess.run(['lpstat', '-p'], capture_output=True, text=True, check=True)
            lines = result.stdout.splitlines()
            for line in lines:
                if line.startswith('printer'):
                    printer_name = line.split(' ')[1]
                    printers.append(printer_name)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"Could not get printers on POSIX system using lpstat: {e}")
            printers.append("Default_Printer_Linux")
    elif os.name == 'nt':  # Windows
        try:
            # Try WMIC first
            result = subprocess.run(['wmic', 'printer', 'get', 'name'], capture_output=True, text=True, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            lines = result.stdout.splitlines()
            for line in lines:
                line = line.strip()
                if line and line.lower() != 'name':
                    printers.append(line)
        except Exception as e:
            logger.warning(f"WMIC failed, trying PowerShell for printer list: {e}")
            try:
                # PowerShell fallback
                ps_cmd = [
                    'powershell',
                    '-Command',
                    "Get-Printer | Select-Object -ExpandProperty Name"
                ]
                result = subprocess.run(ps_cmd, capture_output=True, text=True, check=True)
                lines = result.stdout.splitlines()
                for line in lines:
                    line = line.strip()
                    if line:
                        printers.append(line)
            except Exception as e2:
                logger.error(f"Could not get printers on Windows using PowerShell: {e2}")
                printers.append("Default_Printer_Windows")
    else:
        logger.warning("Unsupported OS for automatic printer detection. Using generic fallback.")
        printers.append("Generic_Printer")

    if not printers:
        logger.warning("No printers detected. Adding a fallback 'Virtual_Printer' option.")
        printers.append("Virtual_Printer")
    return printers

def analyze_message_with_gemini(message_text: str):
    """
    Analyzes the user's message using the Gemini Flash API to extract print settings.
    It constructs a prompt asking Gemini to return a JSON object with specific print parameters.
    Returns a dictionary with 'orientation', 'copies', and 'pages' based on Gemini's analysis.
    """
    prompt = f"""
    You are a helpful assistant that analyzes print requests.
    A user has sent a message along with a file they want to print.
    Your task is to extract the printing settings from the message.

    Extract the following information:
    - **orientation**: "portrait" or "landscape". If not specified, default to "portrait".
    - **copies**: Number of copies. If not specified, default to 1.
    - **pages**: If the document is a PDF and the user mentions specific pages (e.g., "pages 1-3", "page 5"), extract this. Otherwise, return "all".

    Respond ONLY with a JSON object containing these keys.
    Example JSON:
    {{"orientation": "portrait", "copies": 2, "pages": "1-3"}}
    {{"orientation": "landscape", "copies": 1, "pages": "all"}}

    User message: "{message_text}"
    """
    try:
        # Call the Gemini API with the constructed prompt
        response = model.generate_content(prompt)
        # Get the text content from Gemini's response
        response_text = response.text.strip()
        logger.info(f"Gemini raw response: {response_text}")

        # Clean up the response if it contains markdown code block fences (e.g., ```json...```)
        if response_text.startswith("```json") and response_text.endswith("```"):
            response_text = response_text[7:-3].strip() # Remove "```json" from start and "```" from end

        # Parse the cleaned response text as a JSON object
        settings = json.loads(response_text)

        # Validate and set default values for extracted settings
        # Orientation: Ensure it's 'portrait' or 'landscape', default to 'portrait'
        settings['orientation'] = settings.get('orientation', 'portrait').lower()
        if settings['orientation'] not in ['portrait', 'landscape']:
            settings['orientation'] = 'portrait'

        # Copies: Ensure it's an integer and at least 1, default to 1
        settings['copies'] = int(settings.get('copies', 1))
        if settings['copies'] < 1:
            settings['copies'] = 1

        # Pages: Default to 'all' if not specified
        settings['pages'] = settings.get('pages', 'all')

        return settings
    except json.JSONDecodeError as e:
        logger.error(f"Gemini response was not valid JSON: {e}. Response: {response_text if 'response_text' in locals() else 'N/A'}")
        # Fallback if JSON parsing fails
        return {"orientation": "portrait", "copies": 1, "pages": "all"}
    except Exception as e:
        logger.error(f"Error analyzing message with Gemini: {e}", exc_info=True)
        # General fallback for any other errors during Gemini interaction
        return {"orientation": "portrait", "copies": 1, "pages": "all"}

def get_pdf_page_count(file_path: str):
    """
    Returns the number of pages in a PDF file using PyPDF2.
    Returns None if the file is not a valid PDF or an error occurs.
    """
    try:
        with open(file_path, 'rb') as f:
            reader = PdfReader(f)
            return len(reader.pages)
    except Exception as e:
        logger.error(f"Error reading PDF page count for {file_path}: {e}")
        return None

selected_printer_global = None  # Store the selected printer for use by the bot

def cli_select_printer():
    """
    CLI function to list printers, prompt user to select one, and test the printer.
    Returns the selected printer name, or None if selection/test fails.
    """
    printers = get_available_printers()
    if not printers:
        print("No printers found. Exiting.")
        return None
    print("\nAvailable Printers:")
    for idx, printer in enumerate(printers, 1):
        print(f"  {idx}. {printer}")
    while True:
        try:
            choice = int(input(f"Select a printer by number (1-{len(printers)}): "))
            if 1 <= choice <= len(printers):
                selected = printers[choice - 1]
                print(f"You selected: {selected}")
                # Simulate a test print
                print("Testing printer...")
                test_result = submit_print_job_test(selected)
                if test_result:
                    print(f"Test print to '{selected}' succeeded!\n")
                    return selected
                else:
                    print(f"Test print to '{selected}' failed. Try another printer.")
            else:
                print("Invalid selection. Try again.")
        except ValueError:
            print("Please enter a valid number.")

def submit_print_job_test(printer_name):
    """
    Simulate a test print to the selected printer. On Windows, this can be a dummy echo command.
    Returns True if the command succeeds, False otherwise.
    """
    if os.name == 'nt':
        # Simulate with echo (replace with real test if needed)
        command = ['cmd', '/c', 'echo', f"Test print to {printer_name}"]
    else:
        command = ['echo', f"Test print to {printer_name}"]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print(result.stdout.strip())
        return True
    except Exception as e:
        print(f"Error during test print: {e}")
        return False

# Modify submit_print_job to use the global selected_printer_global
# Remove printer selection from Telegram flow

def submit_print_job(file_path: str, printer_name: str, settings: dict):
    """
    Submits a print job to the specified printer with the given settings.
    Uses win32print/win32ui for images, os.startfile for other types on Windows.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if os.name == 'nt' and ext in ['.jpg', '.jpeg', '.png', '.bmp']:
        try:
            img = Image.open(file_path)
            printer_handle = win32print.OpenPrinter(printer_name)
            printer_info = win32print.GetPrinter(printer_handle, 2)
            devmode = printer_info['pDevMode']
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)
            hdc.StartDoc(file_path)
            hdc.StartPage()
            printable_area = hdc.GetDeviceCaps(8), hdc.GetDeviceCaps(10)
            img = img.resize(printable_area, Image.LANCZOS)
            dib = ImageWin.Dib(img)
            dib.draw(hdc.GetHandleOutput(), (0, 0, printable_area[0], printable_area[1]))
            hdc.EndPage()
            hdc.EndDoc()
            hdc.DeleteDC()
            win32print.ClosePrinter(printer_handle)
            logger.info(f"Image '{file_path}' sent to printer '{printer_name}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to print image: {e}")
            return False
    elif os.name == 'nt':
        try:
            logger.info(f"Sending '{file_path}' to printer '{printer_name}' using os.startfile...")
            os.startfile(file_path, f'printto "{printer_name}"')
            logger.info("Print command sent! Check your printer queue.")
            return True
        except Exception as e:
            logger.error(f"Failed to print: {e}")
            return False
    elif os.name == 'posix':
        orientation_arg = "-o landscape" if settings['orientation'] == 'landscape' else ""
        copies_arg = f"-#{settings['copies']}"
        command = ['lpr', '-P', printer_name, copies_arg]
        if orientation_arg:
            command.append(orientation_arg)
        command.append(file_path)
        try:
            logger.info(f"Attempting to execute print command: {' '.join(command)}")
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            logger.info(f"Print command stdout: {result.stdout.strip()}")
            logger.info(f"Print command stderr: {result.stderr.strip()}")
            logger.info(f"Print job submitted for '{file_path}' to '{printer_name}'")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error submitting print job via subprocess (Exit Code: {e.returncode}): {e.stderr.strip()}")
            return False
        except FileNotFoundError:
            logger.error(f"Print command not found. Ensure 'lpr' (Linux/macOS) or appropriate print tools (Windows) are in your system's PATH.")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during printing: {e}", exc_info=True)
            return False
    else:
        logger.error("Unsupported OS for direct printing command. Please implement printing logic for your OS.")
        return False

# --- Local Database and File Management ---
DB_PATH = 'printbot.db'
FILES_DIR = Path('print_files')
FILES_DIR.mkdir(exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS print_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_user TEXT,
        telegram_username TEXT,
        telegram_file_id TEXT,
        original_filename TEXT,
        local_path TEXT,
        datetime TEXT,
        print_settings TEXT,
        status TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

def save_file_and_log_job(file, file_id, original_filename, user, username, print_settings, status):
    # Save file to print_files/original_filename (with unique suffix if needed)
    safe_name = original_filename.replace('/', '_').replace('\\', '_')
    dest_path = FILES_DIR / safe_name
    counter = 1
    while dest_path.exists():
        dest_path = FILES_DIR / f"{Path(safe_name).stem}_{counter}{Path(safe_name).suffix}"
        counter += 1
    with open(dest_path, 'wb') as f:
        f.write(file)
    # Log to DB
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO print_jobs (telegram_user, telegram_username, telegram_file_id, original_filename, local_path, datetime, print_settings, status)
                 VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?)''',
              (user, username, file_id, original_filename, str(dest_path), json.dumps(print_settings), status))
    conn.commit()
    conn.close()
    return str(dest_path)

def list_print_jobs(filter_by=None, value=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = 'SELECT id, telegram_user, telegram_username, original_filename, local_path, datetime, print_settings, status FROM print_jobs'
    params = ()
    if filter_by and value:
        query += f' WHERE {filter_by} = ?'
        params = (value,)
    query += ' ORDER BY datetime DESC'
    c.execute(query, params)
    jobs = c.fetchall()
    conn.close()
    return jobs

# --- Telegram /listfiles command stub ---
from telegram import Update
from telegram.ext import CommandHandler

async def listfiles(update: Update, context):
    jobs = list_print_jobs()
    if not jobs:
        await update.message.reply_text("No print jobs found.")
        return
    msg = "Recent print jobs:\n"
    for job in jobs[:10]:
        msg += f"[{job[0]}] {job[3]} ({job[5]}) - {job[7]}\n"
    await update.message.reply_text(msg)

# --- Telegram Bot Handlers ---
# In handle_file_message, use selected_printer_global instead of asking user
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hello! I'm your print bot. Send me a photo or a PDF document "
        "with a message describing your print settings (e.g., '2 copies, landscape' "
        "or 'print page 5').\n\n"
        "I'll analyze your request and send it to the printer you selected when starting the server."
    )

async def handle_file_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    message_text = update.message.caption if update.message.caption else ""
    # In handle_file_message, support multiple files and per-file settings
    # Assume update.message.photo and update.message.document can be lists
    # 1. Gather all files (photos and documents)
    files = []
    if update.message.photo:
        for idx, photo in enumerate(update.message.photo):
            files.append({
                'file_id': photo.file_id,
                'file_type': 'image',
                'file_name': f'photo_{photo.file_id}.jpg'
            })
    if update.message.document:
        doc = update.message.document
        files.append({
            'file_id': doc.file_id,
            'file_type': 'pdf' if doc.mime_type == 'application/pdf' else 'image',
            'file_name': doc.file_name
        })
    if not files:
        await update.message.reply_text("Please send at least one photo or PDF document for printing.")
        return ConversationHandler.END
    # 2. Parse settings for all files
    print_settings_list = parse_instructions(message_text, len(files))
    log_event(f"Gemini extracted settings: {print_settings_list}")
    # 3. For each file, process and print
    for idx, file_info in enumerate(files):
        file_id = file_info['file_id']
        file_type = file_info['file_type']
        file_name = file_info['file_name']
        # Download file
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file_name}") as temp_file:
            file_path = temp_file.name
            file = await context.bot.get_file(file_id)
            await file.download_to_memory(out=temp_file)
        settings = print_settings_list[idx] if idx < len(print_settings_list) else {}
        processed_file_path = file_path
        if file_type == 'image':
            processed_file_path = process_image(file_path, settings)
            log_event(f"Image processed and saved to: {processed_file_path}")
        # Print file
        print_success = print_file(processed_file_path, selected_printer_global, settings, dry_run=False)
        log_event(f"Print job for file {file_name} success: {print_success}")
        # Clean up
        if os.path.exists(file_path):
            os.unlink(file_path)
        if processed_file_path != file_path and os.path.exists(processed_file_path):
            os.unlink(processed_file_path)
    await update.message.reply_text("All print jobs processed. Check logs for details.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cancels the current operation and ends the conversation.
    Cleans up any temporary files associated with the user.
    """
    user_id = update.effective_user.id
    if user_id in user_data:
        file_path = user_data[user_id].get("file_path")
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
            logger.info(f"Cleaned up temporary file due to cancel: {file_path}")
        del user_data[user_id]

    await update.message.reply_text(
        "Operation cancelled. You can send a new file anytime.",
        reply_markup=ReplyKeyboardRemove() # Remove any active keyboards
    )
    return ConversationHandler.END

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles messages that don't match any specific handler during a conversation.
    Informs the user to select a printer or cancel.
    """
    await update.message.reply_text(
        "I didn't understand that. Please select a printer from the list, "
        "or use /cancel to stop the current print request."
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Logs errors that occur during bot operation and sends a user-friendly message.
    """
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)
    if update.effective_message:
        await update.effective_message.reply_text(
            "An unexpected error occurred! Please try again or contact the bot administrator."
        )

# --- Print Job Queue Worker ---
def process_pending_jobs():
    while True:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, local_path, print_settings, status, original_filename FROM print_jobs WHERE status = 'pending' ORDER BY id ASC LIMIT 1")
        job = c.fetchone()
        if job:
            job_id, local_path, print_settings_json, status, original_filename = job
            try:
                print_settings = json.loads(print_settings_json)
                c.execute("UPDATE print_jobs SET status = 'printing' WHERE id = ?", (job_id,))
                conn.commit()
                log_event(f"[Job {job_id}] Printing {original_filename} with settings: {print_settings}")
                success = print_file(local_path, selected_printer_global, print_settings, dry_run=False)
                if success:
                    c.execute("UPDATE print_jobs SET status = 'done' WHERE id = ?", (job_id,))
                    log_event(f"[Job {job_id}] Print completed.")
                else:
                    c.execute("UPDATE print_jobs SET status = 'failed' WHERE id = ?", (job_id,))
                    log_event(f"[Job {job_id}] Print failed.")
                conn.commit()
            except Exception as e:
                c.execute("UPDATE print_jobs SET status = 'failed' WHERE id = ?", (job_id,))
                conn.commit()
                log_event(f"[Job {job_id}] Print error: {e}")
        conn.close()
        time.sleep(5)  # Check every 5 seconds

# Start the worker thread on startup
worker_thread = threading.Thread(target=process_pending_jobs, daemon=True)
worker_thread.start()

# --- Telegram /jobstatus command ---
async def jobstatus(update: Update, context):
    if not context.args:
        await update.message.reply_text("Usage: /jobstatus <job_id>")
        return
    job_id = context.args[0]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, original_filename, datetime, status FROM print_jobs WHERE id = ?", (job_id,))
    job = c.fetchone()
    conn.close()
    if not job:
        await update.message.reply_text(f"No job found with ID {job_id}.")
        return
    await update.message.reply_text(f"Job {job[0]}: {job[1]}\nTime: {job[2]}\nStatus: {job[3]}")

def main() -> None:
    print("\n==============================")
    print("Welcome to the Telegram Print Bot!")
    print("At startup, you can select a printer from the list of printers available on your Windows PC.")
    print("The app will robustly detect all available printers and allow you to choose before printing.")
    print("==============================\n")
    global selected_printer_global
    selected_printer_global = cli_select_printer()
    if not selected_printer_global:
        print("No valid printer selected. Exiting.")
        return
    print(f"Printer '{selected_printer_global}' will be used for all print jobs. Starting Telegram bot...\n")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.PHOTO | filters.Document.ALL, handle_file_message)
        ],
        states={},  # No printer selection state needed
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, fallback)
        ],
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("listfiles", listfiles)) # Add the new handler
    application.add_handler(CommandHandler("jobstatus", jobstatus)) # Add the new handler
    application.add_error_handler(error_handler)
    logger.info("Telegram Print Bot started. Polling for updates...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
