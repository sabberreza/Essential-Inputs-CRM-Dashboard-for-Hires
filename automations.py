"""
Automation workflows for CRM system
Handles all status change triggers and notifications
"""

import sqlite3
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, Optional
import stripe

class CRMAutomation:
    def __init__(self, db_path='crm_database.db'):
        self.db_path = db_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, str]:
        """Load configuration from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT config_key, config_value FROM config")
        config = dict(cursor.fetchall())
        conn.close()
        return config
    
    def _get_lead_data(self, lead_id: int) -> Optional[Dict]:
        """Fetch lead data from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.*, 
                   c.name as closer_name, c.email as closer_email,
                   p.name as producer_name, p.email as producer_email,
                   lg.name as lead_gen_name, lg.email as lead_gen_email
            FROM leads l
            LEFT JOIN team_members c ON l.assigned_closer_id = c.member_id
            LEFT JOIN team_members p ON l.assigned_producer_id = p.member_id
            LEFT JOIN team_members lg ON lg.role = 'Lead Generator'
            WHERE l.lead_id = ?
        """, (lead_id,))
        
        columns = [description[0] for description in cursor.description]
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(zip(columns, row))
        return None
    
    def _send_email(self, to_email: str, subject: str, body: str) -> bool:
        """Send email via SMTP"""
        smtp_server = self.config.get('smtp_server')
        smtp_email = self.config.get('smtp_email')
        smtp_password = self.config.get('smtp_password')
        
        if not all([smtp_server, smtp_email, smtp_password]):
            print("SMTP not configured")
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = smtp_email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'html'))
            
            server = smtplib.SMTP(smtp_server, 587)
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
            server.quit()
            
            return True
        except Exception as e:
            print(f"Email send failed: {str(e)}")
            return False
    
    def _send_discord(self, message: str, embed_data: Dict = None) -> bool:
        """Send Discord notification"""
        webhook_url = self.config.get('discord_webhook')
        
        if not webhook_url:
            print("Discord webhook not configured")
            return False
        
        payload = {"content": message}
        
        if embed_data:
            embed = {
                "title": embed_data.get('title', 'CRM Notification'),
                "description": embed_data.get('description', ''),
                "color": embed_data.get('color', 3447003),
                "timestamp": datetime.utcnow().isoformat(),
                "fields": embed_data.get('fields', [])
            }
            payload["embeds"] = [embed]
        
        try:
            response = requests.post(webhook_url, json=payload)
            return response.status_code == 204
        except Exception as e:
            print(f"Discord send failed: {str(e)}")
            return False
    
    def _trigger_make_webhook(self, event_type: str, data: Dict) -> bool:
        """Trigger Make.com webhook"""
        webhook_url = self.config.get('make_webhook')
        
        if not webhook_url:
            print("Make.com webhook not configured")
            return False
        
        payload = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        
        try:
            response = requests.post(webhook_url, json=payload)
            return response.status_code == 200
        except Exception as e:
            print(f"Make.com webhook failed: {str(e)}")
            return False
    
    def handle_status_change(self, lead_id: int, old_status: str, new_status: str):
        """Main handler for lead status changes - triggers appropriate workflows"""
        lead_data = self._get_lead_data(lead_id)
        
        if not lead_data:
            return
        
        # Workflow 1: Call Booked → Notify Closer
        if new_status == "Call Booked":
            self._notify_closer_call_booked(lead_data)
        
        # Workflow 2: Deal Closed → Generate Stripe Link
        elif new_status == "Deal Closed":
            self._handle_deal_closed(lead_data)
        
        # Workflow 3: Payment Received → Notify Producer
        elif new_status == "Production Started":
            self._notify_producer_new_project(lead_data)
        
        # Workflow 4: Production Complete → Calculate Commissions
        elif new_status == "Production Complete":
            self._calculate_and_notify_commissions(lead_data)
        
        # Workflow 5: Closed + Paid → Setup Recurring Payment
        elif new_status == "Closed + Paid":
            self._setup_recurring_payment(lead_data)
        
        # Trigger Make.com webhook for all status changes
        self._trigger_make_webhook("status_change", {
            "lead_id": lead_id,
            "old_status": old_status,
            "new_status": new_status,
            "lead_data": lead_data
        })
    
    def _notify_closer_call_booked(self, lead_data: Dict):
        """Workflow 1: Notify closer when call is booked"""
        closer_email = lead_data.get('closer_email')
        closer_name = lead_data.get('closer_name')
        
        if not closer_email:
            return
        
        # Get call details
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT call_datetime, notes_summary 
            FROM calls_meetings 
            WHERE lead_id = ? 
            ORDER BY call_datetime DESC 
            LIMIT 1
        """, (lead_data['lead_id'],))
        call_data = cursor.fetchone()
        conn.close()
        
        call_time = call_data[0] if call_data else "TBD"
        call_notes = call_data[1] if call_data else ""
        
        # Send Email
        subject = f"New Call Booked: {lead_data['lead_name']}"
        body = f"""
        <html>
        <body>
            <h2>New Call Booked</h2>
            <p>Hi {closer_name},</p>
            <p>A new call has been scheduled with you:</p>
            
            <table style="border-collapse: collapse; margin: 20px 0;">
                <tr><td style="padding: 8px; font-weight: bold;">Lead Name:</td><td style="padding: 8px;">{lead_data['lead_name']}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Company:</td><td style="padding: 8px;">{lead_data.get('company_name', 'N/A')}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Email:</td><td style="padding: 8px;">{lead_data.get('contact_email', 'N/A')}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Phone:</td><td style="padding: 8px;">{lead_data.get('contact_phone', 'N/A')}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Scheduled Time:</td><td style="padding: 8px;">{call_time}</td></tr>
            </table>
            
            <p><strong>Notes:</strong><br>{call_notes}</p>
            
            <p>Good luck with the call!</p>
        </body>
        </html>
        """
        
        self._send_email(closer_email, subject, body)
        
        # Send Discord
        self._send_discord(
            f"New Call Booked for {closer_name}",
            {
                'title': 'Call Booked Notification',
                'description': f"Lead: {lead_data['lead_name']} from {lead_data.get('company_name', 'N/A')}",
                'color': 3066993,
                'fields': [
                    {'name': 'Scheduled Time', 'value': call_time, 'inline': True},
                    {'name': 'Contact', 'value': lead_data.get('contact_email', 'N/A'), 'inline': True}
                ]
            }
        )
    
    def _handle_deal_closed(self, lead_data: Dict):
        """Workflow 2: Generate Stripe payment link when deal is closed"""
        # Get deal data
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT deal_id, deal_value 
            FROM deals 
            WHERE lead_id = ? 
            ORDER BY deal_id DESC 
            LIMIT 1
        """, (lead_data['lead_id'],))
        deal_data = cursor.fetchone()
        
        if not deal_data:
            conn.close()
            return
        
        deal_id, deal_value = deal_data
        
        # Generate Stripe payment link
        payment_link = self._create_stripe_payment_link(deal_value, deal_id, lead_data)
        
        # Save payment link to deal
        cursor.execute("""
            UPDATE deals 
            SET stripe_payment_link = ? 
            WHERE deal_id = ?
        """, (payment_link, deal_id))
        conn.commit()
        conn.close()
        
        # Notify closer with payment link
        closer_email = lead_data.get('closer_email')
        if closer_email:
            subject = f"Payment Link Generated: {lead_data['lead_name']}"
            body = f"""
            <html>
            <body>
                <h2>Payment Link Ready</h2>
                <p>The payment link for {lead_data['lead_name']} has been generated:</p>
                
                <p><strong>Deal Value:</strong> ${deal_value:,.2f}</p>
                
                <p><a href="{payment_link}" style="background-color: #5469d4; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block;">Payment Link</a></p>
                
                <p>Share this link with the client to complete the payment.</p>
            </body>
            </html>
            """
            self._send_email(closer_email, subject, body)
    
    def _create_stripe_payment_link(self, amount: float, deal_id: int, lead_data: Dict) -> str:
        """Create Stripe payment link"""
        stripe_key = self.config.get('stripe_api_key')
        
        if not stripe_key:
            # Return placeholder link if Stripe not configured
            return f"https://stripe.com/invoice/pay/{deal_id}"
        
        try:
            stripe.api_key = stripe_key
            
            # Create payment link
            payment_link = stripe.PaymentLink.create(
                line_items=[{
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": int(amount * 100),
                        "product_data": {
                            "name": f"Service for {lead_data['company_name']}",
                        },
                    },
                    "quantity": 1,
                }],
                metadata={
                    "deal_id": deal_id,
                    "lead_id": lead_data['lead_id']
                }
            )
            
            return payment_link.url
        except Exception as e:
            print(f"Stripe payment link creation failed: {str(e)}")
            return f"https://stripe.com/invoice/pay/{deal_id}"
    
    def _notify_producer_new_project(self, lead_data: Dict):
        """Workflow 3: Notify producer when production starts"""
        producer_email = lead_data.get('producer_email')
        producer_name = lead_data.get('producer_name')
        
        if not producer_email:
            return
        
        # Get deal details
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT deal_value 
            FROM deals 
            WHERE lead_id = ? AND payment_status = 'Paid'
            ORDER BY deal_id DESC 
            LIMIT 1
        """, (lead_data['lead_id'],))
        deal_data = cursor.fetchone()
        conn.close()
        
        deal_value = deal_data[0] if deal_data else 0
        
        subject = f"New Production Project: {lead_data['lead_name']}"
        body = f"""
        <html>
        <body>
            <h2>New Production Project Assigned</h2>
            <p>Hi {producer_name},</p>
            <p>A new project has been assigned to you:</p>
            
            <table style="border-collapse: collapse; margin: 20px 0;">
                <tr><td style="padding: 8px; font-weight: bold;">Client:</td><td style="padding: 8px;">{lead_data['lead_name']}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Company:</td><td style="padding: 8px;">{lead_data.get('company_name', 'N/A')}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Deal Value:</td><td style="padding: 8px;">${deal_value:,.2f}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Contact Email:</td><td style="padding: 8px;">{lead_data.get('contact_email', 'N/A')}</td></tr>
                <tr><td style="padding: 8px; font-weight: bold;">Contact Phone:</td><td style="padding: 8px;">{lead_data.get('contact_phone', 'N/A')}</td></tr>
            </table>
            
            <p><strong>Project Notes:</strong><br>{lead_data.get('notes', 'No additional notes')}</p>
            
            <p>Please confirm receipt and start working on this project.</p>
        </body>
        </html>
        """
        
        self._send_email(producer_email, subject, body)
        
        # Send Discord
        self._send_discord(
            f"New Production Project for {producer_name}",
            {
                'title': 'Production Started',
                'description': f"Client: {lead_data['lead_name']} - {lead_data.get('company_name', 'N/A')}",
                'color': 15844367,
                'fields': [
                    {'name': 'Deal Value', 'value': f"${deal_value:,.2f}", 'inline': True},
                    {'name': 'Producer', 'value': producer_name, 'inline': True}
                ]
            }
        )
    
    def _calculate_and_notify_commissions(self, lead_data: Dict):
        """Workflow 4: Calculate commissions when production is complete"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get deal data
        cursor.execute("""
            SELECT deal_id, deal_value 
            FROM deals 
            WHERE lead_id = ? 
            ORDER BY deal_id DESC 
            LIMIT 1
        """, (lead_data['lead_id'],))
        deal_data = cursor.fetchone()
        
        if not deal_data:
            conn.close()
            return
        
        deal_id, deal_value = deal_data
        
        # Calculate commissions
        commission_lead_gen = deal_value * 0.08
        commission_closer = deal_value * 0.10
        commission_producer = deal_value * 0.08
        total_commission = deal_value * 0.26
        
        # Update deal with commission breakdown
        cursor.execute("""
            UPDATE deals 
            SET commission_lead_gen = ?,
                commission_closer = ?,
                commission_producer = ?,
                total_commission = ?
            WHERE deal_id = ?
        """, (commission_lead_gen, commission_closer, commission_producer, total_commission, deal_id))
        conn.commit()
        conn.close()
        
        # Get manager email from config or use default
        manager_email = self.config.get('manager_email', self.config.get('smtp_email'))
        
        if manager_email:
            subject = f"Commission Breakdown: {lead_data['lead_name']}"
            body = f"""
            <html>
            <body>
                <h2>Commission Calculation Complete</h2>
                <p>Production has been completed for {lead_data['lead_name']}. Here's the commission breakdown:</p>
                
                <table style="border-collapse: collapse; margin: 20px 0; border: 1px solid #ddd;">
                    <tr style="background-color: #f2f2f2;">
                        <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Role</th>
                        <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Team Member</th>
                        <th style="padding: 12px; text-align: right; border: 1px solid #ddd;">Commission</th>
                    </tr>
                    <tr>
                        <td style="padding: 12px; border: 1px solid #ddd;">Lead Generator (8%)</td>
                        <td style="padding: 12px; border: 1px solid #ddd;">{lead_data.get('lead_gen_name', 'N/A')}</td>
                        <td style="padding: 12px; text-align: right; border: 1px solid #ddd;">${commission_lead_gen:,.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px; border: 1px solid #ddd;">Closer (10%)</td>
                        <td style="padding: 12px; border: 1px solid #ddd;">{lead_data.get('closer_name', 'N/A')}</td>
                        <td style="padding: 12px; text-align: right; border: 1px solid #ddd;">${commission_closer:,.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px; border: 1px solid #ddd;">Producer (8%)</td>
                        <td style="padding: 12px; border: 1px solid #ddd;">{lead_data.get('producer_name', 'N/A')}</td>
                        <td style="padding: 12px; text-align: right; border: 1px solid #ddd;">${commission_producer:,.2f}</td>
                    </tr>
                    <tr style="background-color: #f2f2f2; font-weight: bold;">
                        <td style="padding: 12px; border: 1px solid #ddd;" colspan="2">Total Commission (26%)</td>
                        <td style="padding: 12px; text-align: right; border: 1px solid #ddd;">${total_commission:,.2f}</td>
                    </tr>
                </table>
                
                <p><strong>Deal Value:</strong> ${deal_value:,.2f}</p>
                <p><strong>Client:</strong> {lead_data['lead_name']} - {lead_data.get('company_name', 'N/A')}</p>
            </body>
            </html>
            """
            
            self._send_email(manager_email, subject, body)
            
            # Send Discord notification
            self._send_discord(
                f"Commission Calculation Complete",
                {
                    'title': 'Commissions Ready',
                    'description': f"Deal: {lead_data['lead_name']} - ${deal_value:,.2f}",
                    'color': 3066993,
                    'fields': [
                        {'name': 'Lead Gen', 'value': f"${commission_lead_gen:,.2f}", 'inline': True},
                        {'name': 'Closer', 'value': f"${commission_closer:,.2f}", 'inline': True},
                        {'name': 'Producer', 'value': f"${commission_producer:,.2f}", 'inline': True},
                        {'name': 'Total', 'value': f"${total_commission:,.2f}", 'inline': False}
                    ]
                }
            )
    
    def _setup_recurring_payment(self, lead_data: Dict):
        """Workflow 5: Setup recurring payment when deal is closed + paid"""
        manager_email = self.config.get('manager_email', self.config.get('smtp_email'))
        
        # Get deal data
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT deal_value 
            FROM deals 
            WHERE lead_id = ? 
            ORDER BY deal_id DESC 
            LIMIT 1
        """, (lead_data['lead_id'],))
        deal_data = cursor.fetchone()
        conn.close()
        
        deal_value = deal_data[0] if deal_data else 0
        
        if manager_email:
            subject = f"Client Fulfilled - Setup Recurring Payment: {lead_data['lead_name']}"
            body = f"""
            <html>
            <body>
                <h2>Client Fulfillment Complete</h2>
                <p>The client {lead_data['lead_name']} has been fully fulfilled.</p>
                
                <p><strong>Action Required:</strong> Setup recurring monthly retainer invoice</p>
                
                <table style="border-collapse: collapse; margin: 20px 0;">
                    <tr><td style="padding: 8px; font-weight: bold;">Client:</td><td style="padding: 8px;">{lead_data['lead_name']}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Company:</td><td style="padding: 8px;">{lead_data.get('company_name', 'N/A')}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Initial Deal Value:</td><td style="padding: 8px;">${deal_value:,.2f}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Contact Email:</td><td style="padding: 8px;">{lead_data.get('contact_email', 'N/A')}</td></tr>
                </table>
                
                <p><strong>Next Steps:</strong></p>
                <ul>
                    <li>Set up recurring monthly invoice in Stripe</li>
                    <li>Send first retainer invoice</li>
                    <li>Add client to active retainer list</li>
                </ul>
                
                <p>This notification was triggered by the completion of production.</p>
            </body>
            </html>
            """
            
            self._send_email(manager_email, subject, body)
            
            # Send Discord
            self._send_discord(
                f"Client Fulfilled - Recurring Payment Needed",
                {
                    'title': 'Setup Recurring Payment',
                    'description': f"Client: {lead_data['lead_name']} is ready for monthly retainer",
                    'color': 5763719,
                    'fields': [
                        {'name': 'Client', 'value': lead_data['lead_name'], 'inline': True},
                        {'name': 'Company', 'value': lead_data.get('company_name', 'N/A'), 'inline': True}
                    ]
                }
            )
    
    def handle_payment_received(self, lead_id: int, deal_id: int):
        """Handle payment received event from Stripe webhook"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Update payment status
        cursor.execute("""
            UPDATE deals 
            SET payment_status = 'Paid' 
            WHERE deal_id = ?
        """, (deal_id,))
        
        # Update lead status to Production Started
        cursor.execute("""
            UPDATE leads 
            SET lead_status = 'Production Started', last_updated = CURRENT_TIMESTAMP 
            WHERE lead_id = ?
        """, (lead_id,))
        
        conn.commit()
        conn.close()
        
        # Trigger production notification
        lead_data = self._get_lead_data(lead_id)
        if lead_data:
            self._notify_producer_new_project(lead_data)
    
    def handle_producer_confirmation(self, lead_id: int):
        """Handle when producer confirms receipt/starts work"""
        # This would be triggered by a webhook or email response
        # For now, it can be called manually or via Make.com
        lead_data = self._get_lead_data(lead_id)
        if lead_data:
            self._calculate_and_notify_commissions(lead_data)

    def log_activity(self, lead_id: int, activity_type: str, performed_by_id: int, notes: str = ""):
        """Log an activity to the activity log"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO activity_log (related_lead_id, activity_type, performed_by_id, notes)
            VALUES (?, ?, ?, ?)
        """, (lead_id, activity_type, performed_by_id, notes))
        conn.commit()
        conn.close()

# Example usage functions
def test_automation():
    """Test automation workflows"""
    automation = CRMAutomation()
    
    # Test notification
    automation._send_discord("Test notification from CRM", {
        'title': 'Test',
        'description': 'This is a test notification',
        'fields': [
            {'name': 'Status', 'value': 'Success', 'inline': True}
        ]
    })

if __name__ == "__main__":
    test_automation()

