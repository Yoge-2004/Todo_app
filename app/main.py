import os
from pathlib import Path
from fastapi import FastAPI, Depends, Request, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from sqlmodel import Session, select
from datetime import date

from .database import create_db_and_tables, get_session
from .models import Task, User, Status, Priority
from .auth import get_password_hash, verify_password

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

# --- EMAIL CONFIG ---
conf = ConnectionConfig(
    MAIL_USERNAME=os.environ.get("MAIL_USERNAME", "your-email@gmail.com"),
    MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD", "your-app-password"),
    MAIL_FROM=os.environ.get("MAIL_USERNAME", "your-email@gmail.com"),
    MAIL_PORT=465,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_STARTTLS=False,
    MAIL_SSL_TLS=True,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
    # vvv ADD THIS LINE vvv
    TEMPLATE_FOLDER=Path(__file__).parent / 'templates' 
)

async def send_email_async(subject: str, email_to: str, body: dict):
    # In production, check if email_to is a valid email address first
    if "@" not in email_to: return
    
    message = MessageSchema(
        subject=subject,
        recipients=[email_to],
        template_body=body,
        subtype=MessageType.html
    )
    fm = FastMail(conf)
    await fm.send_message(message, template_name="email_template.html")

# --- HELPER ---
def get_current_user(request: Request, session: Session):
    user_id = request.cookies.get("user_id")
    if not user_id: return None
    return session.get(User, int(user_id))

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

# --- ROUTES ---
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user: return RedirectResponse(url="/login")
    
    tasks = session.exec(select(Task).where(Task.owner_id == user.id).order_by(Task.deadline)).all()
    return templates.TemplateResponse("index.html", {"request": request, "user": user, "tasks": tasks})

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

    # --- NEW VALIDATION LOGIC ---
    deadline_date = date.fromisoformat(deadline)
    
    if deadline_date < date.today():
        # If date is in the past, stop and send error message
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="flash_msg", value="Error: You cannot add a task for the past!", max_age=5)
        return response
    # -----------------------------

    new_task = Task(title=title, deadline=deadline_date, priority=priority, owner_id=user.id)
    session.add(new_task)
    session.commit()
    
    if priority == "High":
        # Check if username looks like an email before sending
        if "@" in user.username:
            background_tasks.add_task(send_email_async, "High Priority Task", user.username, {"title": title, "deadline": deadline})

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="flash_msg", value="Task added successfully!", max_age=5)
    return response


@app.get("/complete/{task_id}")
def complete_task(task_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    task = session.get(Task, task_id)
    if task and task.owner_id == user.id:
        task.status = Status.COMPLETED if task.status == Status.PENDING else Status.PENDING
        session.add(task)
        session.commit()
    return RedirectResponse(url="/", status_code=303)

@app.get("/delete/{task_id}")
def delete_task(task_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    task = session.get(Task, task_id)
    if task and task.owner_id == user.id:
        session.delete(task)
        session.commit()
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="flash_msg", value="Task deleted", max_age=5)
    return response

# --- AUTH ROUTES ---
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
    if session.exec(select(User).where(User.username == username)).first():
        return templates.TemplateResponse("auth/signup.html", {"request": request, "error": "Username taken"})
    
    new_user = User(username=username, hashed_password=get_password_hash(password))
    session.add(new_user)
    session.commit()
    return RedirectResponse(url="/login", status_code=303)

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("user_id")
    return response

@app.get("/delete_account")
def delete_account(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login")
    
    # 1. Delete all tasks owned by this user
    tasks = session.exec(select(Task).where(Task.owner_id == user.id)).all()
    for task in tasks:
        session.delete(task)
        
    # 2. Delete the user
    session.delete(user)
    session.commit()
    
    # 3. Log out (remove cookie)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("user_id")
    response.set_cookie(key="flash_msg", value="Account deleted successfully.", max_age=5)
    return response
