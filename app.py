import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import json
import requests
from typing import Optional, Dict, Any

# Page configuration
st.set_page_config(
    page_title="Commission CRM System",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Database initialization
def init_database():
    """Initialize SQLite database with all required tables"""
    conn = sqlite3.connect('crm_database.db')
    cursor = conn.cursor()
    
    # Table 1: Leads
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS leads (
        lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_name TEXT NOT NULL,
        company_name TEXT,
        industry TEXT,
        source TEXT,
        contact_email TEXT,
        contact_phone TEXT,
        assigned_closer_id INTEGER,
        assigned_producer_id INTEGER,
        lead_status TEXT DEFAULT 'New Lead',
        notes TEXT,
        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assigned_closer_id) REFERENCES team_members(member_id),
        FOREIGN KEY (assigned_producer_id) REFERENCES team_members(member_id)
    )
    ''')
    
    # Table 2: Calls & Meetings
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS calls_meetings (
        call_id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        call_datetime TIMESTAMP,
        call_outcome TEXT,
        notes_summary TEXT,
        recording_link TEXT,
        FOREIGN KEY (lead_id) REFERENCES leads(lead_id)
    )
    ''')
    
    # Table 3: Deals
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS deals (
        deal_id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        deal_value REAL,
        deal_stage TEXT,
        close_date DATE,
        payment_status TEXT DEFAULT 'Pending',
        stripe_payment_link TEXT,
        commission_lead_gen REAL,
        commission_closer REAL,
        commission_producer REAL,
        total_commission REAL,
        FOREIGN KEY (lead_id) REFERENCES leads(lead_id)
    )
    ''')
    
    # Table 4: Team Members
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS team_members (
        member_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT,
        email TEXT,
        phone TEXT,
        commission_percentage REAL
    )
    ''')
    
    # Table 5: Activity Log
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS activity_log (
        activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
        related_lead_id INTEGER,
        activity_type TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        performed_by_id INTEGER,
        notes TEXT,
        FOREIGN KEY (related_lead_id) REFERENCES leads(lead_id),
        FOREIGN KEY (performed_by_id) REFERENCES team_members(member_id)
    )
    ''')
    
    # Configuration table for API keys and settings
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS config (
        config_key TEXT PRIMARY KEY,
        config_value TEXT
    )
    ''')
    
    conn.commit()
    conn.close()

def calculate_commissions(deal_value: float) -> Dict[str, float]:
    """Calculate commission breakdown"""
    return {
        'lead_gen': deal_value * 0.08,
        'closer': deal_value * 0.10,
        'producer': deal_value * 0.08,
        'total': deal_value * 0.26
    }

# Initialize database
init_database()

# Sidebar navigation
st.sidebar.title("CRM Navigation")
page = st.sidebar.radio(
    "Go to",
    ["Dashboard", "Leads", "Calls & Meetings", "Deals", "Team Members", "Activity Log", "Settings"]
)

# Main content based on page selection
if page == "Dashboard":
    st.title("CRM Dashboard")
    
    col1, col2, col3, col4 = st.columns(4)
    
    conn = sqlite3.connect('crm_database.db')
    
    # Metrics
    total_leads = pd.read_sql_query("SELECT COUNT(*) as count FROM leads", conn)['count'][0]
    active_deals = pd.read_sql_query("SELECT COUNT(*) as count FROM deals WHERE deal_stage != 'Lost'", conn)['count'][0]
    total_revenue = pd.read_sql_query("SELECT COALESCE(SUM(deal_value), 0) as total FROM deals WHERE payment_status = 'Paid'", conn)['total'][0]
    pending_payments = pd.read_sql_query("SELECT COUNT(*) as count FROM deals WHERE payment_status = 'Pending'", conn)['count'][0]
    
    col1.metric("Total Leads", total_leads)
    col2.metric("Active Deals", active_deals)
    col3.metric("Total Revenue", f"${total_revenue:,.2f}")
    col4.metric("Pending Payments", pending_payments)
    
    st.subheader("Recent Leads")
    recent_leads = pd.read_sql_query("""
        SELECT lead_id, lead_name, company_name, lead_status, date_added 
        FROM leads 
        ORDER BY date_added DESC 
        LIMIT 10
    """, conn)
    st.dataframe(recent_leads, use_container_width=True)
    
    st.subheader("Pipeline Overview")
    pipeline_data = pd.read_sql_query("""
        SELECT lead_status, COUNT(*) as count 
        FROM leads 
        GROUP BY lead_status
    """, conn)
    if not pipeline_data.empty:
        st.bar_chart(pipeline_data.set_index('lead_status'))
    
    conn.close()

elif page == "Leads":
    st.title("Lead Management")
    
    tab1, tab2 = st.tabs(["View Leads", "Add New Lead"])
    
    with tab1:
        conn = sqlite3.connect('crm_database.db')
        leads_df = pd.read_sql_query("""
            SELECT l.*, 
                   c.name as closer_name,
                   p.name as producer_name
            FROM leads l
            LEFT JOIN team_members c ON l.assigned_closer_id = c.member_id
            LEFT JOIN team_members p ON l.assigned_producer_id = p.member_id
            ORDER BY l.date_added DESC
        """, conn)
        
        if not leads_df.empty:
            st.dataframe(leads_df, use_container_width=True)
            
            # Lead selection for editing
            st.subheader("Update Lead Status")
            lead_to_update = st.selectbox("Select Lead", leads_df['lead_id'].tolist(), format_func=lambda x: leads_df[leads_df['lead_id']==x]['lead_name'].values[0])
            
            if lead_to_update:
                current_lead = leads_df[leads_df['lead_id'] == lead_to_update].iloc[0]
                
                status_options = [
                    "New Lead", "Notified Closer", "Call Booked", "Call Confirmed",
                    "Deal Closed", "Production Started", "Production Complete", "Closed + Paid"
                ]
                
                new_status = st.selectbox("New Status", status_options, index=status_options.index(current_lead['lead_status']))
                
                if st.button("Update Status"):
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE leads 
                        SET lead_status = ?, last_updated = CURRENT_TIMESTAMP 
                        WHERE lead_id = ?
                    """, (new_status, lead_to_update))
                    conn.commit()
                    st.success(f"Lead status updated to: {new_status}")
                    st.rerun()
        else:
            st.info("No leads found. Add your first lead in the 'Add New Lead' tab.")
        
        conn.close()
    
    with tab2:
        with st.form("new_lead_form"):
            st.subheader("Add New Lead")
            
            col1, col2 = st.columns(2)
            
            with col1:
                lead_name = st.text_input("Lead Name*")
                company_name = st.text_input("Company Name")
                industry = st.selectbox("Industry", ["Tech", "Construction", "Healthcare", "Education", "Finance", "Other"])
                source = st.selectbox("Source", ["Cold Outreach", "Referral", "Website Form", "Social Media", "Other"])
            
            with col2:
                contact_email = st.text_input("Contact Email")
                contact_phone = st.text_input("Contact Phone")
                
                conn = sqlite3.connect('crm_database.db')
                team_members = pd.read_sql_query("SELECT member_id, name, role FROM team_members", conn)
                conn.close()
                
                closers = team_members[team_members['role'] == 'Closer']
                producers = team_members[team_members['role'] == 'Producer']
                
                assigned_closer = st.selectbox("Assigned Closer", [None] + closers['member_id'].tolist(), format_func=lambda x: "Unassigned" if x is None else closers[closers['member_id']==x]['name'].values[0] if x in closers['member_id'].values else "")
                assigned_producer = st.selectbox("Assigned Producer", [None] + producers['member_id'].tolist(), format_func=lambda x: "Unassigned" if x is None else producers[producers['member_id']==x]['name'].values[0] if x in producers['member_id'].values else "")
            
            notes = st.text_area("Notes")
            
            submitted = st.form_submit_button("Add Lead")
            
            if submitted and lead_name:
                conn = sqlite3.connect('crm_database.db')
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO leads (lead_name, company_name, industry, source, contact_email, contact_phone, assigned_closer_id, assigned_producer_id, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (lead_name, company_name, industry, source, contact_email, contact_phone, assigned_closer, assigned_producer, notes))
                conn.commit()
                conn.close()
                
                st.success(f"Lead '{lead_name}' added successfully!")
                st.rerun()

elif page == "Team Members":
    st.title("Team Management")
    
    tab1, tab2 = st.tabs(["View Team", "Add Team Member"])
    
    with tab1:
        conn = sqlite3.connect('crm_database.db')
        team_df = pd.read_sql_query("SELECT * FROM team_members ORDER BY role, name", conn)
        conn.close()
        
        if not team_df.empty:
            st.dataframe(team_df, use_container_width=True)
        else:
            st.info("No team members added yet.")
    
    with tab2:
        with st.form("new_team_member_form"):
            st.subheader("Add Team Member")
            
            col1, col2 = st.columns(2)
            
            with col1:
                name = st.text_input("Name*")
                role = st.selectbox("Role", ["Lead Generator", "Closer", "Producer", "Manager"])
            
            with col2:
                email = st.text_input("Email")
                phone = st.text_input("Phone")
            
            # Auto-fill commission based on role
            role_commissions = {
                "Lead Generator": 8.0,
                "Closer": 10.0,
                "Producer": 8.0,
                "Manager": 0.0
            }
            commission_percentage = st.number_input(
                "Commission %",
                value=role_commissions.get(role, 0.0),
                min_value=0.0,
                max_value=100.0,
                step=0.5
            )
            
            submitted = st.form_submit_button("Add Team Member")
            
            if submitted and name:
                conn = sqlite3.connect('crm_database.db')
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO team_members (name, role, email, phone, commission_percentage)
                    VALUES (?, ?, ?, ?, ?)
                """, (name, role, email, phone, commission_percentage))
                conn.commit()
                conn.close()
                
                st.success(f"Team member '{name}' added successfully!")
                st.rerun()

elif page == "Deals":
    st.title("Deal Management")
    
    tab1, tab2 = st.tabs(["View Deals", "Create New Deal"])
    
    with tab1:
        conn = sqlite3.connect('crm_database.db')
        deals_df = pd.read_sql_query("""
            SELECT d.*, l.lead_name, l.company_name
            FROM deals d
            LEFT JOIN leads l ON d.lead_id = l.lead_id
            ORDER BY d.deal_id DESC
        """, conn)
        conn.close()
        
        if not deals_df.empty:
            st.dataframe(deals_df, use_container_width=True)
            
            # Deal statistics
            col1, col2, col3 = st.columns(3)
            with col1:
                won_deals = deals_df[deals_df['deal_stage'] == 'Won']['deal_value'].sum()
                st.metric("Won Deals Value", f"${won_deals:,.2f}")
            with col2:
                pending_deals = deals_df[deals_df['deal_stage'].isin(['Proposal Sent', 'Negotiation'])]['deal_value'].sum()
                st.metric("Pipeline Value", f"${pending_deals:,.2f}")
            with col3:
                total_commissions = deals_df['total_commission'].sum()
                st.metric("Total Commissions", f"${total_commissions:,.2f}")
        else:
            st.info("No deals created yet.")
    
    with tab2:
        with st.form("new_deal_form"):
            st.subheader("Create New Deal")
            
            conn = sqlite3.connect('crm_database.db')
            leads_df = pd.read_sql_query("SELECT lead_id, lead_name, company_name FROM leads", conn)
            conn.close()
            
            if not leads_df.empty:
                lead_id = st.selectbox(
                    "Select Lead",
                    leads_df['lead_id'].tolist(),
                    format_func=lambda x: f"{leads_df[leads_df['lead_id']==x]['lead_name'].values[0]} - {leads_df[leads_df['lead_id']==x]['company_name'].values[0]}"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    deal_value = st.number_input("Deal Value ($)", min_value=0.0, step=100.0)
                    deal_stage = st.selectbox("Deal Stage", ["Proposal Sent", "Negotiation", "Won", "Lost"])
                with col2:
                    close_date = st.date_input("Expected Close Date")
                    payment_status = st.selectbox("Payment Status", ["Pending", "Paid", "Overdue"])
                
                # Show commission preview
                if deal_value > 0:
                    st.subheader("Commission Preview")
                    commissions = calculate_commissions(deal_value)
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Lead Gen (8%)", f"${commissions['lead_gen']:,.2f}")
                    col2.metric("Closer (10%)", f"${commissions['closer']:,.2f}")
                    col3.metric("Producer (8%)", f"${commissions['producer']:,.2f}")
                    col4.metric("Total (26%)", f"${commissions['total']:,.2f}")
                
                submitted = st.form_submit_button("Create Deal")
                
                if submitted and deal_value > 0:
                    commissions = calculate_commissions(deal_value)
                    
                    conn = sqlite3.connect('crm_database.db')
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO deals (
                            lead_id, deal_value, deal_stage, close_date, payment_status,
                            commission_lead_gen, commission_closer, commission_producer, total_commission
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        lead_id, deal_value, deal_stage, close_date, payment_status,
                        commissions['lead_gen'], commissions['closer'], 
                        commissions['producer'], commissions['total']
                    ))
                    
                    # Update lead status if deal is won
                    if deal_stage == "Won":
                        cursor.execute("""
                            UPDATE leads 
                            SET lead_status = 'Deal Closed', last_updated = CURRENT_TIMESTAMP
                            WHERE lead_id = ?
                        """, (lead_id,))
                    
                    conn.commit()
                    conn.close()
                    
                    st.success("Deal created successfully!")
                    st.rerun()
            else:
                st.warning("Please add leads first before creating deals.")

elif page == "Settings":
    st.title("Settings & Configuration")
    
    # Authentication for Settings page
    if 'settings_authenticated' not in st.session_state:
        st.session_state.settings_authenticated = False
    
    if not st.session_state.settings_authenticated:
        st.subheader("Authentication Required")
        
        with st.form("login_form"):
            st.write("Please enter your credentials to access settings:")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            login_submitted = st.form_submit_button("Login")
            
            if login_submitted:
                if username == "sabberreza" and password == "3Hthegame":
                    st.session_state.settings_authenticated = True
                    st.success("Authentication successful!")
                    st.rerun()
                else:
                    st.error("Invalid username or password. Please try again.")
        
        st.stop()
    
    # Settings content (only shown if authenticated)
    st.subheader("API Keys & Webhooks")
    
    # Logout button
    if st.button("Logout"):
        st.session_state.settings_authenticated = False
        st.rerun()
    
    with st.form("settings_form"):
        discord_webhook = st.text_input("Discord Webhook URL", type="password")
        make_webhook = st.text_input("Make.com Webhook URL", type="password")
        stripe_api_key = st.text_input("Stripe API Key", type="password")
        smtp_server = st.text_input("SMTP Server")
        smtp_email = st.text_input("SMTP Email")
        smtp_password = st.text_input("SMTP Password", type="password")
        
        submitted = st.form_submit_button("Save Settings")
        
        if submitted:
            conn = sqlite3.connect('crm_database.db')
            cursor = conn.cursor()
            
            settings = {
                'discord_webhook': discord_webhook,
                'make_webhook': make_webhook,
                'stripe_api_key': stripe_api_key,
                'smtp_server': smtp_server,
                'smtp_email': smtp_email,
                'smtp_password': smtp_password
            }
            
            for key, value in settings.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO config (config_key, config_value) 
                    VALUES (?, ?)
                """, (key, value))
            
            conn.commit()
            conn.close()
            
            st.success("Settings saved successfully!")

# Footer
st.sidebar.markdown("---")
st.sidebar.info("Commission CRM System v1.0")