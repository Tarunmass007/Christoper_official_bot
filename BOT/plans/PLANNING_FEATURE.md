# Christopher Planning Feature Documentation

## Overview
This feature allows users to view available subscription plans and request them directly through the bot. The owner can then approve or deny requests with ease.

## User Commands

### `/plans`
Display all available subscription plans with pricing, features, and duration.

**Example:**
```
/plans
```

**Features shown:**
- Plan name and badge
- Pricing
- Duration
- Credits allocation
- Anti-spam settings
- Mass operation limits
- Special features

### `/requestplan [plan_name]`
Submit a request for a specific plan.

**Usage:**
```
/requestplan Pro
/requestplan Elite
```

**Available plans:**
- Plus ($1 - 1 Day)
- Pro ($6 - 7 Days)
- Elite ($9 - 15 Days)
- VIP ($15 - 30 Days)
- Ultimate ($25 - 60 Days)

**Process:**
1. User submits request
2. Owner receives notification
3. User contacts @Chr1shtopher for payment
4. Owner approves request after payment verification
5. Owner activates plan using existing commands

### `/myrequests`
View your plan request history and current status.

**Status types:**
- ⏳ Pending - Waiting for owner approval
- ✅ Approved - Request approved, plan will be activated
- ❌ Denied - Request denied with reason

### `/cancelrequest`
Cancel your pending plan request if you change your mind.

## Owner Commands

### `/listrequests`
View all plan requests (pending, approved, denied).

**Features:**
- Shows user ID, name, username
- Displays requested plan
- Organized by status

### `/approveplan [user_id]`
Approve a user's plan request.

**Usage:**
```
/approveplan 123456789
```

**What happens:**
1. Request marked as approved
2. User receives approval notification
3. Owner reminded to activate plan using existing commands

**Next steps after approval:**
```
/plus 123456789    # For Plus plan
/pro 123456789     # For Pro plan
/elite 123456789   # For Elite plan
/vip 123456789     # For VIP plan
/ult 123456789     # For Ultimate plan
```

### `/denyplan [user_id] [reason]`
Deny a user's plan request with optional reason.

**Usage:**
```
/denyplan 123456789 Payment not received
/denyplan 123456789
```

**What happens:**
1. Request marked as denied
2. User receives denial notification with reason
3. Request removed from pending list

## Interactive Buttons

### Plan Request Buttons
When using `/plans`, users can request plans using inline buttons:
- Request Plus
- Request Pro
- Request Elite
- Request VIP
- Request Ultimate

### Owner Approval Buttons
When notified of a new request, owner sees:
- ✅ Approve - Approve the request
- ❌ Deny - Deny the request
- View All Requests - See all pending requests

## Workflow Example

### User Flow:
```
1. User: /plans
   → Sees all available plans

2. User: /requestplan Pro
   → Request submitted
   → Owner notified

3. User contacts @Chr1shtopher for payment

4. User: /myrequests
   → Checks request status

5. Owner approves after payment
   → User receives approval notification

6. Owner activates plan
   → User receives activation notification
```

### Owner Flow:
```
1. Receives notification of new request
   → Shows user details and requested plan

2. Verifies payment with user

3. Option A - Using buttons:
   → Click "✅ Approve" button

4. Option B - Using command:
   → /approveplan [user_id]

5. Activate the plan:
   → /pro [user_id]

6. User receives plan activation confirmation
```

## Data Storage

Plan requests are stored in: `DATA/plan_requests.json`

**Structure:**
```json
{
  "user_id": {
    "user_id": 123456789,
    "username": "username",
    "first_name": "John",
    "plan": "Pro",
    "requested_at": "2026-01-17 12:34:56",
    "status": "pending",
    "approved_at": "2026-01-17 12:45:00",
    "reason": "Payment verified"
  }
}
```

## Plan Details

### Plus Plan ($1 - 1 Day)
- 💠 Badge
- 200 Credits
- 13s Anti-Spam
- 5 Mass Limit
- All Gates Access
- Priority Support

### Pro Plan ($6 - 7 Days)
- 🔰 Badge
- 500 Credits
- 10s Anti-Spam
- 10 Mass Limit
- All Gates Access
- Premium Support
- Private Mode

### Elite Plan ($9 - 15 Days)
- 🔷 Badge
- 800 Credits
- 8s Anti-Spam
- 15 Mass Limit
- All Gates Access
- VIP Support
- Private Mode
- Custom Requests

### VIP Plan ($15 - 30 Days)
- 👑 Badge
- 1500 Credits
- 5s Anti-Spam
- 25 Mass Limit
- All Gates Access
- 24/7 VIP Support
- Private Mode
- Custom Gates
- Priority Processing

### Ultimate Plan ($25 - 60 Days)
- 👑 Badge
- Unlimited Credits
- 3s Anti-Spam
- 50 Mass Limit
- All Gates Access
- Dedicated Support
- Private Mode
- Custom Everything
- API Access

## Integration with Existing System

This feature works seamlessly with the existing plan activation system:
- Does not replace existing owner commands (`/plus`, `/pro`, etc.)
- Adds user-facing visibility and request management
- Owner still has full control over plan activation
- Compatible with facility owner restrictions
- Integrates with existing notification system

## Security Features

- Only owner can approve/deny requests
- User can only see their own requests
- Prevents duplicate pending requests
- Validates plan names before submission
- Secure file locking for concurrent operations
- Request status tracking prevents duplicate processing

## Future Enhancements (Optional)

Possible additions:
- Payment gateway integration for automatic activation
- Request expiry after X days
- Plan upgrade/downgrade requests
- Bulk approval for multiple requests
- Request statistics and analytics
- Email/webhook notifications
- Custom plan creation for special users
