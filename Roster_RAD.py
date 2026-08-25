import streamlit as st
import calendar
import pandas as pd
import time
from datetime import datetime
from ortools.sat.python import cp_model

# --- 1. THE OR-TOOLS CP-SAT ALGORITHM ---
def generate_roster(year, month, total_employees, time_off_requests=None, public_holidays=None):
    if time_off_requests is None:
        time_off_requests = {}
    if public_holidays is None:
        public_holidays = []
        
    if total_employees < 3:
        raise ValueError(f"Insufficient staff. Minimum of 3 required.")

    _, num_days = calendar.monthrange(year, month)
    employees = [f"Emp_{i+1}" for i in range(total_employees)]
    
    model = cp_model.CpModel()
    
    # Create Variables
    shifts = {}
    for emp in employees:
        for day in range(1, num_days + 1):
            shifts[(emp, day)] = model.NewBoolVar(f"shift_{emp}_d{day}")
            
    # Hard Constraints
    for day in range(1, num_days + 1):
        model.Add(sum(shifts[(emp, day)] for emp in employees) == 1)
        
    for emp in employees:
        for day in time_off_requests.get(emp, []):
            if 1 <= day <= num_days:
                model.Add(shifts[(emp, day)] == 0)
                
    for emp in employees:
        for day in range(1, num_days - 1):
            model.Add(shifts[(emp, day)] + shifts[(emp, day+1)] + shifts[(emp, day+2)] <= 1)
            
    # Objective: Balance Workloads for Fairness
    total_shifts = {}
    weekend_shifts = {}
    
    premium_days = set([
        d for d in range(1, num_days + 1) 
        if calendar.weekday(year, month, d) >= 5 or d in public_holidays
    ])
    
    for emp in employees:
        total_shifts[emp] = sum(shifts[(emp, day)] for day in range(1, num_days + 1))
        weekend_shifts[emp] = sum(shifts[(emp, day)] for day in premium_days)
        
    min_shifts = model.NewIntVar(0, num_days, 'min_shifts')
    max_shifts = model.NewIntVar(0, num_days, 'max_shifts')
    model.AddMinEquality(min_shifts, [total_shifts[emp] for emp in employees])
    model.AddMaxEquality(max_shifts, [total_shifts[emp] for emp in employees])
    
    min_weekend = model.NewIntVar(0, num_days, 'min_weekend')
    max_weekend = model.NewIntVar(0, num_days, 'max_weekend')
    model.AddMinEquality(min_weekend, [weekend_shifts[emp] for emp in employees])
    model.AddMaxEquality(max_weekend, [weekend_shifts[emp] for emp in employees])
    
    model.Minimize((max_shifts - min_shifts) * 10 + (max_weekend - min_weekend))
    
    # Solve the Model
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0 
    status = solver.Solve(model)
    
    # Parse Results for the UI
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        roster = {}
        shift_counts = {emp: 0 for emp in employees}
        weekend_counts = {emp: 0 for emp in employees}
        
        for day in range(1, num_days + 1):
            assigned = []
            is_premium_day = day in premium_days 
            
            for emp in employees:
                if solver.Value(shifts[(emp, day)]) == 1:
                    assigned.append(emp)
                    shift_counts[emp] += 1
                    if is_premium_day:
                        weekend_counts[emp] += 1
                        
            roster[day] = assigned
            
        return roster, shift_counts, weekend_counts
    else:
        raise ValueError("No feasible schedule exists with these constraints.")

# --- 2. THE UI FRAMEWORK ---
st.set_page_config(page_title="Shift Roster Generator", layout="wide")
st.title("Shift Roster Calendar Generator")

# Sidebar Configuration
with st.sidebar:
    st.header("Roster Settings")
    current_year = datetime.now().year
    current_month = datetime.now().month
    year = st.number_input("Year", min_value=current_year, max_value=2099, value=current_year)
    month = st.selectbox("Month", range(1, 13), format_func=lambda x: calendar.month_name[x], index=current_month % 12)
    total_employees = st.slider("Total Employees", 3, 20, 5)
    
    st.markdown("---")
    st.header("Global Rules")
    holidays_str = st.text_input("Public Holidays (Dates)", placeholder="e.g. 4, 10, 25")
    
    public_holidays = []
    if holidays_str:
        public_holidays = [int(d.strip()) for d in holidays_str.split(",") if d.strip().isdigit()]

# Main Page: Blackout Dates
st.subheader("Time-Off Requests (Blackout Dates)")
st.caption("Enter the dates (1-31) an employee cannot work, separated by commas.")

time_off_requests = {}
cols = st.columns(4) 

for i in range(total_employees):
    emp_name = f"Emp_{i+1}"
    with cols[i % 4]:
        dates_str = st.text_input(emp_name, key=emp_name)
        if dates_str:
            clean_dates = [int(d.strip()) for d in dates_str.split(",") if d.strip().isdigit()]
            time_off_requests[emp_name] = clean_dates

st.markdown("---")
if st.button("Generate Roster", type="primary"):
    start_time = time.time()
    
    try:
        schedule, total_shifts, weekend_shifts = generate_roster(
            year, month, total_employees, time_off_requests, public_holidays
        )
        
        solve_time = time.time() - start_time
        st.success(f"Roster successfully generated in {solve_time:.4f} seconds!")
        
        # Give the calendar slightly more room by adjusting the column ratio
        col1, col2 = st.columns([2.5, 1])
        
        with col1:
            st.subheader(f"Calendar: {calendar.month_name[month]} {year}")
            
            # 1. Fetch the 2D array of weeks/days for the given month
            cal_matrix = calendar.monthcalendar(year, month)
            weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            
            # 2. Build the grid row by row
            calendar_data = []
            for week in cal_matrix:
                week_dict = {}
                for i, day in enumerate(week):
                    if day == 0:
                        # Day belongs to previous/next month
                        week_dict[weekdays[i]] = ""
                    else:
                        workers = schedule.get(day, [])
                        staff_str = ", ".join(workers)
                        marker = " 🌟" if day in public_holidays else ""
                        
                        # Use line breaks (\n) to stack the date above the staff name
                        week_dict[weekdays[i]] = f"{day}{marker}\n{staff_str}"
                
                calendar_data.append(week_dict)
                
            # 3. Render the 7-day grid using Streamlit's dataframe
            df_cal = pd.DataFrame(calendar_data)
            st.dataframe(df_cal, use_container_width=True, hide_index=True)
            
        with col2:
            st.subheader("Workload Distribution")
            stats_data = []
            for emp in total_shifts.keys():
                stats_data.append({
                    "Employee": emp,
                    "Total Shifts": total_shifts[emp],
                    "Premium Shifts (Wknd/Hol)": weekend_shifts[emp]
                })
            st.dataframe(pd.DataFrame(stats_data), use_container_width=True, hide_index=True)

    except ValueError as e:
        solve_time = time.time() - start_time
        st.error(f"Failed after {solve_time:.4f} seconds.")
        st.error(f"Error: {e}")
