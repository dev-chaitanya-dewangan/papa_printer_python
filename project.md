# Telegram Print Bot

## High-level Architecture

```mermaid
[Frontend] -> [API Server] -> [Print Queue Manager] -> [Printer]
```

## Modules and Responsibilities

1. **Frontend**

   - Handles user interface and input
   - Manages authentication
   - Provides a simple way to submit print jobs

2. **API Server**

   - Acts as a gateway for print requests
   - Validates user authentication
   - Receives print job requests and stores them in the queue

3. **Print Queue Manager**

   - Manages the print job queue
   - Assigns jobs to available printers
   - Tracks job status and progress

4. **Printer**
   - Receives print jobs from the queue
   - Processes the print job (e.g., PDF to image conversion, page range)
   - Sends print output to the printer

## Database Schema

```sql
-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Print jobs table
CREATE TABLE print_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    file_path VARCHAR(512) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Printer status table
CREATE TABLE printer_status (
    id SERIAL PRIMARY KEY,
    printer_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

## File/Folder Structure

```
project/
├── frontend/
│   ├── app.py
│   ├── templates/
│   ├── static/
│   └── requirements.txt
├── api/
│   ├── app.py
│   ├── routes/
│   ├── models/
│   └── requirements.txt
├── print_queue/
│   ├── manager.py
│   ├── printer_simulator.py
│   └── requirements.txt
├── printer/
│   ├── printer_driver.py
│   └── requirements.txt
├── database/
│   ├── models.py
│   ├── utils.py
│   └── requirements.txt
├── tests/
├── logs/
├── config/
└── README.md
```

## Key Requirements

- **Python Packages**:

  - Flask for API server
  - Celery for task queue
  - PyPDF2 for PDF processing
  - Pillow for image processing
  - Selenium for browser automation (if needed)
  - Requests for HTTP requests
  - SQLAlchemy for database ORM
  - WTForms for form validation

- **Operating System**:

  - Linux (recommended for printer drivers)
  - Windows (for frontend/API)
  - macOS (for frontend/API)

- **Printer Support**:
  - PDF to Image conversion (e.g., PDFium, Poppler)
  - Page range selection
  - Cloud printing (if implemented)
  - Direct printer connection (if supported)

## Print Queue and Job Status System

1. **Job Submission**:

   - User submits a print job via the frontend
   - Frontend sends a request to the API server
   - API server validates user and stores job in the database

2. **Job Assignment**:

   - Print Queue Manager monitors the queue
   - Assigns available jobs to printers
   - Updates job status to "Processing"

3. **Job Processing**:

   - Printer receives the job
   - Processes the file (PDF to image, page range)
   - Updates job status to "Completed" or "Failed"

4. **Job Status Updates**:
   - Frontend polls the API server for job status
   - API server returns current status and progress
   - User can cancel the job if needed

## How to Extend/Upgrade

1. **Add PDF Page Range**:

   - Modify PDF processing to handle page ranges
   - Update job submission form to accept page range
   - Update job processing to apply page range

2. **Cloud Printing**:

   - Implement a cloud printing service (e.g., Google Cloud Print, CUPS)
   - Modify printer drivers to use cloud services
   - Update job submission to use cloud print API

3. **User Authentication**:
   - Add user registration and login
   - Secure API endpoints
   - Store user-specific print jobs

## Learning Resources

1. **Frontend**:

   - Flask documentation
   - WTForms documentation
   - HTML/CSS/JavaScript basics
   - Bootstrap for responsive design

2. **API Server**:

   - Flask-RESTful documentation
   - SQLAlchemy documentation
   - Celery documentation
   - PDF processing libraries (PyPDF2, Poppler)

3. **Print Queue Manager**:

   - Celery documentation
   - PDF processing libraries (PyPDF2, Poppler)
   - Printer drivers (if direct connection)

4. **Printer**:
   - Printer driver development (if direct connection)
   - Cloud printing API documentation (if cloud)

## Example Usage Flows

1. **Basic Print Job**:

   - User logs in
   - Navigates to print page
   - Selects file and page range
   - Clicks "Print"
   - Frontend sends job to API server
   - API server validates and stores job
   - Queue Manager assigns job to printer
   - Printer processes and prints
   - User sees job status on frontend

2. **Cloud Print Job**:
   - User logs in
   - Navigates to print page
   - Selects file and page range
   - Clicks "Print"
   - Frontend sends job to API server
   - API server validates and stores job
   - Queue Manager assigns job to printer
   - Printer processes and prints via cloud service
   - User sees job status on frontend

## Important Notes for Maintainers/Contributors

1. **Error Handling**:

   - Comprehensive error logging
   - User-friendly error messages
   - Graceful degradation for printer failures

2. **Performance**:

   - Efficient PDF processing
   - Fast job status updates
   - Scalable architecture

3. **Security**:

   - Secure API endpoints
   - User authentication
   - File upload security

4. **Scalability**:

   - Use Celery for background tasks
   - Distribute printers across multiple servers
   - Implement load balancing

5. **Documentation**:
   - Clear and concise code comments
   - Comprehensive README.md
   - Detailed API documentation

```

```
