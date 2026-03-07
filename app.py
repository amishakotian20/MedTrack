from flask import Flask, render_template, request, redirect, url_for, session, flash
import boto3
from boto3.dynamodb.conditions import Attr
import uuid
import hashlib
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'medtrack-secret-key-2024')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

# ─── SNS TOPIC ARN ─────────────────────────────────────────
SNS_TOPIC_ARN = 'arn:aws:sns:us-east-1:746669240044:MedTrack_SNS'

# ─── ADMIN CREDENTIALS ─────────────────────────────────────
ADMIN_EMAIL    = 'admin@medtrack.com'
ADMIN_PASSWORD = 'admin123'

def get_dynamodb():
    return boto3.resource('dynamodb', region_name=AWS_REGION)

def get_sns():
    return boto3.client('sns', region_name=AWS_REGION)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def send_notification(subject, message):
    try:
        sns = get_sns()
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message
        )
    except Exception as e:
        print(f'SNS notification failed: {str(e)}')

# ─── DECORATORS ────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def patient_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'patient':
            flash('Access denied. Patients only.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def doctor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'doctor':
            flash('Access denied. Doctors only.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Access denied. Admins only.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ─── DOCTOR DATA ───────────────────────────────────────────
DOCTORS = [
    {'id': 'D01', 'name': 'Dr. Ananya Sharma',  'specialty': 'General Physician', 'fee': 500,  'slots': ['9:00 AM', '10:00 AM', '11:00 AM', '2:00 PM', '3:00 PM']},
    {'id': 'D02', 'name': 'Dr. Rohan Mehta',    'specialty': 'Cardiologist',       'fee': 1000, 'slots': ['10:00 AM', '11:00 AM', '4:00 PM', '5:00 PM']},
    {'id': 'D03', 'name': 'Dr. Priya Nair',     'specialty': 'Dermatologist',      'fee': 700,  'slots': ['9:00 AM', '12:00 PM', '2:00 PM', '4:00 PM']},
    {'id': 'D04', 'name': 'Dr. Kiran Reddy',    'specialty': 'Orthopedist',        'fee': 800,  'slots': ['10:00 AM', '11:00 AM', '3:00 PM', '5:00 PM']},
    {'id': 'D05', 'name': 'Dr. Sunita Patel',   'specialty': 'Pediatrician',       'fee': 600,  'slots': ['9:00 AM', '10:00 AM', '1:00 PM', '3:00 PM']},
]

# ─── HOME ──────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

# ─── REGISTER ──────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name     = request.form['name'].strip()
        email    = request.form['email'].strip().lower()
        password = request.form['password']

        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('register.html')
        try:
            db    = get_dynamodb()
            table = db.Table('Patients')
            response = table.scan(FilterExpression=Attr('Email').eq(email))
            if response['Items']:
                flash('Email already registered. Please login.', 'warning')
                return render_template('register.html')

            patient_id = str(uuid.uuid4())
            table.put_item(Item={
                'PatientID': patient_id,
                'Name':      name,
                'Email':     email,
                'Password':  hash_password(password),
                'Role':      'patient'
            })

            # SNS notification
            send_notification(
                subject='Welcome to MedTrack!',
                message=f'Dear {name},\n\nWelcome to MedTrack! Your account has been created successfully.\n\nEmail: {email}\n\nYou can now login and book appointments.\n\nTeam MedTrack'
            )

            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'danger')

    return render_template('register.html')

# ─── LOGIN ─────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email'].strip().lower()
        password = request.form['password']
        role     = request.form['role']

        # Admin login
        if role == 'admin':
            if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
                session['user_id']   = 'admin'
                session['user_name'] = 'Admin'
                session['role']      = 'admin'
                flash('Welcome, Admin!', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid admin credentials.', 'danger')

        # Doctor login
        elif role == 'doctor':
            try:
                db    = get_dynamodb()
                table = db.Table('Doctors')
                response = table.scan(FilterExpression=Attr('Email').eq(email))
                items = response['Items']
                if items and items[0]['Password'] == hash_password(password):
                    doctor = items[0]
                    session['user_id']   = doctor['DoctorID']
                    session['user_name'] = doctor['Name']
                    session['role']      = 'doctor'
                    flash(f"Welcome, {doctor['Name']}!", 'success')
                    return redirect(url_for('doctor_dashboard'))
                else:
                    flash('Invalid doctor credentials.', 'danger')
            except Exception as e:
                flash(f'Login failed: {str(e)}', 'danger')

        # Patient login
        elif role == 'patient':
            try:
                db    = get_dynamodb()
                table = db.Table('Patients')
                response = table.scan(FilterExpression=Attr('Email').eq(email))
                items = response['Items']
                if items and items[0]['Password'] == hash_password(password):
                    patient = items[0]
                    session['user_id']      = patient['PatientID']
                    session['user_name']    = patient['Name']
                    session['role']         = 'patient'
                    session['patient_id']   = patient['PatientID']
                    session['patient_name'] = patient['Name']
                    flash(f"Welcome, {patient['Name']}!", 'success')
                    return redirect(url_for('dashboard'))
                else:
                    flash('Invalid patient credentials.', 'danger')
            except Exception as e:
                flash(f'Login failed: {str(e)}', 'danger')

    return render_template('login.html')

# ─── LOGOUT ────────────────────────────────────────────────
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# ─── PATIENT DASHBOARD ─────────────────────────────────────
@app.route('/dashboard')
@login_required
@patient_required
def dashboard():
    try:
        db    = get_dynamodb()
        table = db.Table('Appointments')
        response = table.scan(FilterExpression=Attr('PatientID').eq(session['patient_id']))
        appointments = sorted(response['Items'], key=lambda x: x.get('Date', ''), reverse=True)
    except Exception as e:
        appointments = []
        flash(f'Could not load appointments: {str(e)}', 'warning')
    return render_template('dashboard.html', appointments=appointments)

# ─── DOCTOR DASHBOARD ──────────────────────────────────────
@app.route('/doctor/dashboard')
@login_required
@doctor_required
def doctor_dashboard():
    try:
        db    = get_dynamodb()
        response = db.Table('Appointments').scan(
            FilterExpression=Attr('Doctor').eq(session['user_name'])
        )
        appointments = sorted(response['Items'], key=lambda x: x.get('Date', ''), reverse=True)

        patients_table = db.Table('Patients')
        for appt in appointments:
            try:
                p = patients_table.get_item(Key={'PatientID': appt['PatientID']})
                appt['PatientName'] = p['Item']['Name'] if 'Item' in p else 'Unknown'
            except:
                appt['PatientName'] = 'Unknown'

    except Exception as e:
        appointments = []
        flash(f'Could not load appointments: {str(e)}', 'warning')
    return render_template('doctor_dashboard.html', appointments=appointments)

@app.route('/doctor/update/<appointment_id>', methods=['POST'])
@login_required
@doctor_required
def update_appointment(appointment_id):
    status = request.form['status']
    try:
        db = get_dynamodb()

        # Get appointment details first
        appt = db.Table('Appointments').get_item(Key={'AppointmentID': appointment_id})
        appt_item = appt.get('Item', {})

        db.Table('Appointments').update_item(
            Key={'AppointmentID': appointment_id},
            UpdateExpression='SET #s = :val',
            ExpressionAttributeNames={'#s': 'Status'},
            ExpressionAttributeValues={':val': status}
        )

        # SNS notification to patient
        send_notification(
            subject=f'MedTrack — Appointment {status}',
            message=f'Dear Patient,\n\nYour appointment with {appt_item.get("Doctor", "your doctor")} on {appt_item.get("Date", "")} has been marked as {status}.\n\nPlease login to MedTrack for more details.\n\nTeam MedTrack'
        )

        flash(f'Appointment marked as {status}.', 'success')
    except Exception as e:
        flash(f'Update failed: {str(e)}', 'danger')
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/lab-reports')
@login_required
@doctor_required
def doctor_lab_reports():
    try:
        db = get_dynamodb()
        response = db.Table('LabReports').scan()
        reports = sorted(response['Items'], key=lambda x: x.get('Date', ''), reverse=True)

        patients_table = db.Table('Patients')
        for rep in reports:
            try:
                p = patients_table.get_item(Key={'PatientID': rep['PatientID']})
                rep['PatientName'] = p['Item']['Name'] if 'Item' in p else 'Unknown'
            except:
                rep['PatientName'] = 'Unknown'
    except Exception as e:
        reports = []
        flash(f'Could not load reports: {str(e)}', 'warning')
    return render_template('doctor_lab_reports.html', reports=reports)

# ─── ADMIN DASHBOARD ───────────────────────────────────────
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    try:
        db = get_dynamodb()
        patients     = db.Table('Patients').scan()['Items']
        appointments = db.Table('Appointments').scan()['Items']
        bills        = db.Table('Billing').scan()['Items']
        reports      = db.Table('LabReports').scan()['Items']
    except Exception as e:
        patients = appointments = bills = reports = []
        flash(f'Could not load data: {str(e)}', 'warning')
    return render_template('admin_dashboard.html',
        patients=patients,
        appointments=appointments,
        bills=bills,
        reports=reports
    )

# ─── SCHEDULES ─────────────────────────────────────────────
@app.route('/schedules')
@login_required
@patient_required
def schedules():
    return render_template('schedules.html', doctors=DOCTORS)

# ─── BOOK APPOINTMENT ──────────────────────────────────────
@app.route('/book', methods=['GET', 'POST'])
@login_required
@patient_required
def book_appointment():
    if request.method == 'POST':
        doctor = request.form['doctor']
        date   = request.form['date']
        slot   = request.form['slot']
        fee    = request.form['fee']

        if not doctor or not date or not slot:
            flash('Please fill all fields.', 'danger')
            return render_template('book.html', doctors=DOCTORS)
        try:
            db      = get_dynamodb()
            appt_id = str(uuid.uuid4())
            db.Table('Appointments').put_item(Item={
                'AppointmentID': appt_id,
                'PatientID':     session['patient_id'],
                'Doctor':        doctor,
                'Date':          date,
                'Slot':          slot,
                'Status':        'Pending'
            })
            bill_id = str(uuid.uuid4())
            db.Table('Billing').put_item(Item={
                'BillID':        bill_id,
                'PatientID':     session['patient_id'],
                'AppointmentID': appt_id,
                'Doctor':        doctor,
                'Date':          date,
                'Amount':        fee,
                'PaymentStatus': 'Unpaid'
            })

            # SNS notification
            send_notification(
                subject='MedTrack — Appointment Booked!',
                message=f'Dear {session["patient_name"]},\n\nYour appointment has been booked successfully!\n\nDoctor: {doctor}\nDate: {date}\nTime Slot: {slot}\nConsultation Fee: Rs.{fee}\nStatus: Pending\n\nPlease arrive 10 minutes early.\n\nTeam MedTrack'
            )

            flash('Appointment booked and bill generated!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Booking failed: {str(e)}', 'danger')

    return render_template('book.html', doctors=DOCTORS)

# ─── CANCEL APPOINTMENT ────────────────────────────────────
@app.route('/cancel/<appointment_id>', methods=['POST'])
@login_required
@patient_required
def cancel_appointment(appointment_id):
    try:
        db = get_dynamodb()

        # Get appointment details
        appt = db.Table('Appointments').get_item(Key={'AppointmentID': appointment_id})
        appt_item = appt.get('Item', {})

        db.Table('Appointments').update_item(
            Key={'AppointmentID': appointment_id},
            UpdateExpression='SET #s = :val',
            ExpressionAttributeNames={'#s': 'Status'},
            ExpressionAttributeValues={':val': 'Cancelled'}
        )

        # SNS notification
        send_notification(
            subject='MedTrack — Appointment Cancelled',
            message=f'Dear {session["patient_name"]},\n\nYour appointment with {appt_item.get("Doctor", "your doctor")} on {appt_item.get("Date", "")} has been cancelled.\n\nYou can book a new appointment anytime.\n\nTeam MedTrack'
        )

        flash('Appointment cancelled.', 'info')
    except Exception as e:
        flash(f'Cancel failed: {str(e)}', 'danger')
    return redirect(url_for('dashboard'))

# ─── MEDICAL HISTORY ───────────────────────────────────────
@app.route('/medical-history')
@login_required
@patient_required
def medical_history():
    try:
        db = get_dynamodb()
        response = db.Table('Appointments').scan(
            FilterExpression=Attr('PatientID').eq(session['patient_id'])
        )
        records = sorted(response['Items'], key=lambda x: x.get('Date', ''), reverse=True)
    except Exception as e:
        records = []
        flash(f'Could not load history: {str(e)}', 'warning')
    return render_template('history.html', records=records)

# ─── LAB REPORTS ───────────────────────────────────────────
@app.route('/lab-reports', methods=['GET', 'POST'])
@login_required
@patient_required
def lab_reports():
    if request.method == 'POST':
        test_name = request.form['test_name'].strip()
        result    = request.form['result'].strip()
        date      = request.form['date']
        notes     = request.form.get('notes', '').strip()

        if not test_name or not result or not date:
            flash('Please fill all required fields.', 'danger')
        else:
            try:
                db        = get_dynamodb()
                report_id = str(uuid.uuid4())
                db.Table('LabReports').put_item(Item={
                    'ReportID':  report_id,
                    'PatientID': session['patient_id'],
                    'TestName':  test_name,
                    'Result':    result,
                    'Date':      date,
                    'Notes':     notes
                })

                # SNS notification
                send_notification(
                    subject='MedTrack — Lab Report Submitted',
                    message=f'Dear {session["patient_name"]},\n\nYour lab report has been submitted successfully!\n\nTest: {test_name}\nResult: {result}\nDate: {date}\n\nYour doctor will review it shortly.\n\nTeam MedTrack'
                )

                flash('Lab report submitted!', 'success')
                return redirect(url_for('lab_reports'))
            except Exception as e:
                flash(f'Failed: {str(e)}', 'danger')

    try:
        db = get_dynamodb()
        response = db.Table('LabReports').scan(
            FilterExpression=Attr('PatientID').eq(session['patient_id'])
        )
        reports = sorted(response['Items'], key=lambda x: x.get('Date', ''), reverse=True)
    except Exception as e:
        reports = []
        flash(f'Could not load reports: {str(e)}', 'warning')
    return render_template('lab_reports.html', reports=reports)

# ─── BILLING ───────────────────────────────────────────────
@app.route('/billing')
@login_required
@patient_required
def billing():
    try:
        db = get_dynamodb()
        response = db.Table('Billing').scan(
            FilterExpression=Attr('PatientID').eq(session['patient_id'])
        )
        bills = sorted(response['Items'], key=lambda x: x.get('Date', ''), reverse=True)
    except Exception as e:
        bills = []
        flash(f'Could not load bills: {str(e)}', 'warning')
    return render_template('billing.html', bills=bills)

@app.route('/pay/<bill_id>', methods=['POST'])
@login_required
@patient_required
def pay_bill(bill_id):
    try:
        db = get_dynamodb()

        # Get bill details
        bill = db.Table('Billing').get_item(Key={'BillID': bill_id})
        bill_item = bill.get('Item', {})

        db.Table('Billing').update_item(
            Key={'BillID': bill_id},
            UpdateExpression='SET PaymentStatus = :val',
            ExpressionAttributeValues={':val': 'Paid'}
        )

        # SNS notification
        send_notification(
            subject='MedTrack — Payment Successful',
            message=f'Dear {session["patient_name"]},\n\nYour payment has been received!\n\nDoctor: {bill_item.get("Doctor", "")}\nDate: {bill_item.get("Date", "")}\nAmount Paid: Rs.{bill_item.get("Amount", "")}\nStatus: Paid\n\nThank you for using MedTrack.\n\nTeam MedTrack'
        )

        flash('Payment successful!', 'success')
    except Exception as e:
        flash(f'Payment failed: {str(e)}', 'danger')
    return redirect(url_for('billing'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)