"""
Webhook handler for CRM system
Handles incoming webhooks from external services like Stripe
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, Any
import requests
from automations import CRMAutomation

def handle_stripe_webhook(payload: Dict[str, Any]) -> bool:
    """
    Handle incoming Stripe webhook for payment events
    
    Args:
        payload: Stripe webhook payload
        
    Returns:
        bool: True if webhook was processed successfully
    """
    try:
        event_type = payload.get('type')
        
        if event_type == 'payment_intent.succeeded':
            # Payment was successful
            payment_intent = payload.get('data', {}).get('object', {})
            metadata = payment_intent.get('metadata', {})
            
            deal_id = metadata.get('deal_id')
            lead_id = metadata.get('lead_id')
            
            if deal_id and lead_id:
                automation = CRMAutomation()
                automation.handle_payment_received(int(lead_id), int(deal_id))
                return True
        
        elif event_type == 'payment_intent.payment_failed':
            # Payment failed
            payment_intent = payload.get('data', {}).get('object', {})
            metadata = payment_intent.get('metadata', {})
            
            deal_id = metadata.get('deal_id')
            lead_id = metadata.get('lead_id')
            
            if deal_id and lead_id:
                # Update payment status to failed
                conn = sqlite3.connect('crm_database.db')
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE deals 
                    SET payment_status = 'Failed' 
                    WHERE deal_id = ?
                """, (deal_id,))
                conn.commit()
                conn.close()
                
                # Log the failed payment
                automation = CRMAutomation()
                automation.log_activity(
                    int(lead_id), 
                    'Payment Failed', 
                    0,  # System user
                    f"Payment failed for deal {deal_id}"
                )
                return True
        
        return False
        
    except Exception as e:
        print(f"Error handling Stripe webhook: {str(e)}")
        return False

def handle_make_webhook(payload: Dict[str, Any]) -> bool:
    """
    Handle incoming webhook from Make.com
    
    Args:
        payload: Make.com webhook payload
        
    Returns:
        bool: True if webhook was processed successfully
    """
    try:
        event_type = payload.get('event_type')
        
        if event_type == 'producer_confirmation':
            # Producer confirmed receipt of project
            lead_id = payload.get('data', {}).get('lead_id')
            
            if lead_id:
                automation = CRMAutomation()
                automation.handle_producer_confirmation(int(lead_id))
                return True
        
        elif event_type == 'manual_status_update':
            # Manual status update from external system
            lead_id = payload.get('data', {}).get('lead_id')
            new_status = payload.get('data', {}).get('new_status')
            old_status = payload.get('data', {}).get('old_status')
            
            if lead_id and new_status:
                automation = CRMAutomation()
                automation.handle_status_change(int(lead_id), old_status, new_status)
                return True
        
        return False
        
    except Exception as e:
        print(f"Error handling Make.com webhook: {str(e)}")
        return False

def log_webhook_event(webhook_type: str, payload: Dict[str, Any], success: bool):
    """
    Log webhook events for debugging and monitoring
    
    Args:
        webhook_type: Type of webhook (stripe, make, etc.)
        payload: Webhook payload
        success: Whether processing was successful
    """
    try:
        conn = sqlite3.connect('crm_database.db')
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO activity_log (related_lead_id, activity_type, performed_by_id, notes)
            VALUES (?, ?, ?, ?)
        """, (
            0,  # System event
            f'Webhook_{webhook_type}',
            0,  # System user
            f"Success: {success}, Payload: {json.dumps(payload)[:500]}"
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"Error logging webhook event: {str(e)}")

# Example Flask/Streamlit webhook endpoint
def create_webhook_endpoint():
    """
    Example of how to create webhook endpoints
    This would typically be used with Flask or similar framework
    """
    
    def stripe_webhook_endpoint(request_data):
        """Stripe webhook endpoint"""
        success = handle_stripe_webhook(request_data)
        log_webhook_event('stripe', request_data, success)
        return {'status': 'success' if success else 'error'}
    
    def make_webhook_endpoint(request_data):
        """Make.com webhook endpoint"""
        success = handle_make_webhook(request_data)
        log_webhook_event('make', request_data, success)
        return {'status': 'success' if success else 'error'}
    
    return stripe_webhook_endpoint, make_webhook_endpoint

if __name__ == "__main__":
    # Test webhook handling
    test_stripe_payload = {
        'type': 'payment_intent.succeeded',
        'data': {
            'object': {
                'metadata': {
                    'deal_id': '1',
                    'lead_id': '1'
                }
            }
        }
    }
    
    print("Testing Stripe webhook handling...")
    result = handle_stripe_webhook(test_stripe_payload)
    print(f"Result: {result}")
    
    test_make_payload = {
        'event_type': 'producer_confirmation',
        'data': {
            'lead_id': '1'
        }
    }
    
    print("Testing Make.com webhook handling...")
    result = handle_make_webhook(test_make_payload)
    print(f"Result: {result}")