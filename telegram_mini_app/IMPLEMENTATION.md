# Telegram Mini App Implementation Plan

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Telegram Mini App (TWA)                                        │
├─────────────────────────────────────────────────────────────────┤
│  Frontend: Next.js 14 + TypeScript + TailwindCSS (dark mode)   │
│  ├─ App.tsx (root layout, initData validation)                 │
│  ├─ pages/dashboard.tsx (balance, positions, risk, alerts)     │
│  ├─ pages/portfolio.tsx (detailed positions, analytics)        │
│  ├─ pages/alerts.tsx (active alerts, settings)                 │
│  ├─ pages/premium.tsx (features, subscription, Stars)          │
│  ├─ components/BalanceCard, PositionsTable, AlertCard, etc.    │
│  └─ lib/twa.ts (WebApp SDK integration, haptics)               │
├─────────────────────────────────────────────────────────────────┤
│  Backend: FastAPI (Python)                                      │
│  ├─ twa_backend.py (webhook handler, TWA bridge, premium check)│
│  ├─ twa_types.py (Pydantic models, initData validation)        │
│  ├─ message_router.py (text/voice intent detection)            │
│  ├─ risk_checker.py (safety checks before execution)           │
│  ├─ alert_system.py (critical alerts, notifications)           │
│  ├─ revenue.py (premium entitlements, Stars integration)       │
│  └─ audit_logger.py (all critical actions)                     │
├─────────────────────────────────────────────────────────────────┤
│  Integration with main bot (telegram_agent.py)                  │
│  ├─ Preserve all existing commands & callbacks                 │
│  ├─ Add TWA-specific endpoints via FastAPI                     │
│  ├─ Reuse existing auth (invite-only system)                   │
│  └─ Emergency stop always available                            │
└─────────────────────────────────────────────────────────────────┘
```

## Key Principles (DO NOT BREAK)

1. **Backward Compatibility**: Old bot commands continue working exactly as before
2. **Security First**: All initData validated server-side, no trusting frontend
3. **Idempotency**: All risky operations use idempotency keys
4. **Graceful Degradation**: If TWA fails, old bot still works
5. **Emergency Override**: Stop/emergency commands ALWAYS available
6. **Server-Side Gating**: Premium checks only on backend
7. **Audit Trail**: Every critical action logged
8. **Haptic Feedback**: Not intrusive, optional, enhances UX

## Implementation Steps

### Phase 1: Secure Backend Foundation
- [x] InitData validator (SHA256 + freshness check)
- [x] TWAResponse schema (unified response format)
- [x] Error handling & fallback routing
- [ ] **Message router** (text/voice intent detection)
- [ ] **Risk checker** (position close, limit orders, etc.)
- [ ] **Alert system** (critical events, notifications)
- [ ] **Audit logger** (SQLite, immutable log)

### Phase 2: Frontend Foundation
- [ ] Next.js 14 project scaffold
- [ ] Telegram WebApp SDK integration
- [ ] TailwindCSS dark mode theme
- [ ] Layout with Telegram-safe navigation
- [ ] Error boundary & loading states

### Phase 3: Core Features
- [ ] Dashboard (balance, positions, PnL, risk)
- [ ] Portfolio page (detailed analytics)
- [ ] Alerts (active, settings, premium)
- [ ] Confirm modal (for risky operations)
- [ ] Premium card (features, purchase)

### Phase 4: Message Routing & Safety
- [ ] Text message router (ask AI, trade, get info)
- [ ] Voice message transcription & routing
- [ ] Risk checking before execution
- [ ] Idempotency key handling
- [ ] Atomic transactions

### Phase 5: Premium & Revenue
- [ ] Premium feature gating
- [ ] Stars payment integration
- [ ] Subscription model
- [ ] One-time purchases
- [ ] Entitlement verification

### Phase 6: Alerts & Retention
- [ ] Critical event alerting
- [ ] Daily/weekly digest
- [ ] Auto-return triggers
- [ ] Notification preferences
- [ ] Deep linking to TWA

### Phase 7: Integration & Testing
- [ ] Connect frontend to backend
- [ ] Test all old bot commands (preserve)
- [ ] Test TWA flows
- [ ] Test premium gating
- [ ] Smoke tests & e2e

## File Structure

```
/root/my_personal_ai/
├── telegram_mini_app/
│   ├── frontend/                          # Next.js app
│   │   ├── app/
│   │   │   ├── layout.tsx                # Root layout
│   │   │   ├── page.tsx                  # Dashboard
│   │   │   └── globals.css
│   │   ├── app/dashboard/
│   │   │   └── page.tsx
│   │   ├── app/portfolio/
│   │   │   └── page.tsx
│   │   ├── app/alerts/
│   │   │   └── page.tsx
│   │   ├── app/premium/
│   │   │   └── page.tsx
│   │   ├── components/
│   │   │   ├── BalanceCard.tsx
│   │   │   ├── PositionsTable.tsx
│   │   │   ├── AlertCard.tsx
│   │   │   ├── ConfirmModal.tsx
│   │   │   ├── PremiumCard.tsx
│   │   │   ├── LoadingSkeleton.tsx
│   │   │   ├── ErrorBoundary.tsx
│   │   │   └── Navbar.tsx
│   │   ├── lib/
│   │   │   ├── twa.ts                    # WebApp SDK wrapper
│   │   │   ├── api.ts                    # Backend API client
│   │   │   ├── hooks.ts                  # React hooks
│   │   │   └── types.ts                  # Shared types
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── tailwind.config.js
│   │   └── next.config.js
│   │
│   ├── backend/
│   │   ├── twa_backend.py                # Main FastAPI app
│   │   ├── twa_types.py                  # Pydantic models
│   │   ├── message_router.py             # TEXT/VOICE routing
│   │   ├── risk_checker.py               # Safety checks
│   │   ├── alert_system.py               # Alerts & notifications
│   │   ├── revenue.py                    # Premium, Stars, entitlements
│   │   ├── audit_logger.py               # Immutable audit log
│   │   └── __init__.py
│   │
│   ├── twa_backend.py                    # (legacy, will import from backend/)
│   ├── twa_types.py                      # (legacy, will import from backend/)
│   ├── revenue.py                        # (legacy, will import from backend/)
│   ├── __init__.py
│   └── IMPLEMENTATION.md
│
├── agents/
│   └── telegram_agent.py                 # UNCHANGED
│
└── main.py                               # UNCHANGED
```

## Response Schema (Unified)

All TWA handlers return this format:

```json
{
  "status": "execute|clarify|deny|error|widget",
  "title": "Operation Name",
  "message": "Human-readable explanation",
  
  "widgetType": "balance|position|chart|alert|confirm|risk|status|premium|none",
  "data": {
    // Widget-specific data
  },
  
  "action": "execute|cancel|retry",
  "requiresConfirmation": false,
  "idempotencyKey": "uuid",
  "entitlementRequired": false,
  
  "error": null,
  "errorCode": null
}
```

### Status Codes
- **execute**: Safe to execute, no confirmation needed
- **clarify**: Need more info (show form/input)
- **deny**: Action not allowed (insufficient funds, premium required, etc.)
- **error**: System error (retry)
- **widget**: Show interactive widget (balance, position, alert, premium, confirm)

## Security Checklist

- [ ] initData validated on every request
- [ ] hash checked with HMAC-SHA256
- [ ] auth_date freshness checked (< 5 min)
- [ ] All operations idempotent
- [ ] Audit log for all critical actions
- [ ] No trusting client-side data
- [ ] Premium checks server-side only
- [ ] CORS restricted to Telegram WebApp
- [ ] Rate limiting on sensitive endpoints
- [ ] Old bot commands preserved
- [ ] Emergency stop always accessible

## Backward Compatibility

- Old `/start`, `/help`, `/status`, `/balance`, etc. commands **unchanged**
- Old callback handlers **preserved**
- Old text message routing **fallback** if new router fails
- Old voice routing **fallback** if new router fails
- Emergency stop command **always available** (no premium gating)
- Old database schema **compatible**
- Old webhook format **unchanged**

## Testing Strategy

1. **Unit tests**: Router, risk checker, validator
2. **Integration tests**: Frontend + backend API
3. **Smoke tests**: Old commands still work
4. **Security tests**: initData validation, XSS, CSRF
5. **Load tests**: Concurrent users, haptics
6. **E2E tests**: Full user flow (auth → buy → trade → alert)

## Deployment

1. Update `requirements.txt` with new dependencies
2. Deploy backend first (FastAPI + validators)
3. Deploy frontend next (Next.js static + API)
4. Run smoke tests
5. Monitor logs for errors
6. Keep rollback plan ready

## Monitoring & Observability

- Error rates by endpoint
- Premium feature usage
- Alert trigger counts
- Revenue metrics
- User retention
- Audit log queries
- Performance P95/P99

---

**Key Constraint**: ALL changes are opt-in. Old bot is the default. New features are enhancements, not replacements.
