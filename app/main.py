import os
import smtplib  # Standard Python Email Library (Stable)
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import date, datetime

from fastapi import FastAPI, Depends, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

# Import local modules
from .database import create_db_and_tables, get_session
from .models import Task, User, Status, Priority
from .auth import get_password_hash, verify_password

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

# --- 1. EMAIL FUNCTION (Fixed for Render Blocking) ---
def send_email_sync(subject: str, email_to: str, body_data: dict):
    """
    Sends email using SMTP_SSL on Port 465.
    This bypasses the [Errno 101] block on Port 587.
    """
    sender = os.environ.get("MAIL_USERNAME")
    password = os.environ.get("MAIL_PASSWORD")
    
    if not sender or not password:
        print("Error: Email credentials missing.")
        return

    try:
        # Create the email object
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = email_to
        msg['Subject'] = subject

        # Create HTML Body
        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
                <h2 style="color: #4f46e5;">Task Notification</h2>
                <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; border-left: 5px solid #4f46e5;">
                    <p><strong>Task:</strong> {body_data.get('title')}</p>
                    <p><strong>Deadline:</strong> {body_data.get('deadline')}</p>
                    <p><strong>Priority:</strong> <span style="color: red;">High</span></p>
                </div>
                <p>Get it done!</p>
            </body>
        </html>
        """
        msg.attach(MIMEText(html_content, 'html'))

        # --- THE FIX IS HERE ---
        # Use SMTP_SSL directly on Port 465
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        
        # Note: server.starttls() is NOT needed for SMTP_SSL
        
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent successfully to {email_to}")
        
    except Exception as e:
        print(f"❌ FAILED to send email: {e}")


# --- 2. AUTH HELPERS ---
def get_current_user(request: Request, session: Session):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    return session.get(User, int(user_id))


# --- 3. STARTUP EVENT ---
@app.on_event("startup")
def on_startup():
    create_db_and_tables()


# --- 4. APP ROUTES ---
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login")
    
    tasks = session.exec(select(Task).where(Task.owner_id == user.id).order_by(Task.deadline)).all()
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": user, 
        "tasks": tasks, 
        "Priority": Priority, 
        "Status": Status
    })


@app.post("/add")
async def add_task(
    background_tasks: BackgroundTasks,
    request: Request,
    title: str = Form(...),
    deadline: str = Form(...),
    priority: str = Form(...),
    session: Session = Depends(get_session)
):
    user = get_current_user(request, session)
    if not user: return RedirectResponse(url="/login")

    # VALIDATION: Check for past dates
    try:
        deadline_date = date.fromisoformat(deadline)
        if deadline_date < date.today():
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie(key="flash_msg", value="Error: Cannot add tasks in the past!", max_age=5)
            return response
    except ValueError:
        return RedirectResponse(url="/", status_code=303)

    # Save Task
    new_task = Task(title=title, deadline=deadline_date, priority=priority, owner_id=user.id)
    session.add(new_task)
    session.commit()
    
    # EMAIL LOGIC: Only send if Priority is High and Username is an Email
    if priority == "High" and "@" in user.username:
        background_tasks.add_task(
            send_email_sync, 
            "High Priority Task Assigned", 
            user.username, 
            {"title": title, "deadline": deadline}
        )

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="flash_msg", value="Task added successfully!", max_age=5)
    return response


@app.get("/complete/{task_id}")
def complete_task(task_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user: return RedirectResponse(url="/login")

    task = session.get(Task, task_id)
    if task and task.owner_id == user.id:
        if task.status == Status.PENDING:
            task.status = Status.COMPLETED
        else:
            task.status = Status.PENDING
        session.add(task)
        session.commit()
        
    return RedirectResponse(url="/", status_code=303)


@app.get("/delete/{task_id}")
def delete_task(task_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user: return RedirectResponse(url="/login")

    task = session.get(Task, task_id)
    if task and task.owner_id == user.id:
        session.delete(task)
        session.commit()
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="flash_msg", value="Task deleted", max_age=5)
    return response


@app.get("/delete_account")
def delete_account(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user: return RedirectResponse(url="/login")
    
    # 1. Delete all tasks owned by this user
    tasks = session.exec(select(Task).where(Task.owner_id == user.id)).all()
    for task in tasks:
        session.delete(task)
        
    # 2. Delete the user
    session.delete(user)
    session.commit()
    
    # 3. Log out
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("user_id")
    response.set_cookie(key="flash_msg", value="Account deleted successfully.", max_age=5)
    return response


# --- 5. AUTH ROUTES ---
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == username)).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("auth/login.html", {"request": request, "error": "Invalid credentials"})
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="user_id", value=str(user.id))
    return response


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse("auth/signup.html", {"request": request})


@app.post("/signup")
def signup(request: Request, username: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
    existing_user = session.exec(select(User).where(User.username == username)).first()
    if existing_user:
        return templates.TemplateResponse("auth/signup.html", {"request": request, "error": "Username already taken"})
    
    new_user = User(username=username, hashed_password=get_password_hash(password))
    session.add(new_user)
    session.commit()
    
    return RedirectResponse(url="/login", status_code=303)


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("user_id")
    return response
    
