# NIGHT SHIFT PREP — AYKA Transport Logistics
**Date:** 2026-03-19 | **Prepared by:** Claude Code (Sonnet 4.6)

---

## ✅ COMPLETED TONIGHT (Bug Fixes Applied)

| # | Task | File(s) Changed | Status |
|---|------|----------------|--------|
| 1 | **ORD-000** — Sequential order numbers | `Dashboard_SaaS/src/pages/Orders.tsx:132` | ✅ Fixed |
| 2 | **Add Driver** — Wrong password update + missing emailRedirectTo | `Dashboard_SaaS/src/pages/Drivers.tsx:123, 149` | ✅ Fixed |
| 3 | **Password Reset** — Driver lands on admin dashboard after reset | `DriverResetPassword.tsx:17`, `ResetPassword.tsx:34` | ✅ Fixed |
| 4 | **Route Optimization** — `'in_cleaning'` filter blocked all delivery orders | `Dashboard_SaaS/src/pages/RouteCreation.tsx:100` | ✅ Fixed |

---

## 🌐 TASK 5 — Multi-Language Audit (TR / FR / EN / NL / DE)

### 5.1 — CRITICAL: German (DE) Missing from Driver App

**File:** `Driver_app/lib/translations.ts`
**File:** `Driver_app/contexts/LanguageContext.tsx`

The Driver_app `LanguageContext` defines only 4 languages (`'tr' | 'en' | 'fr' | 'nl'`). German (`de`) is **completely absent** — no locale object, no type entry, no language picker option.

The Dashboard_SaaS already has a full DE locale in its `LanguageContext.tsx`. The Driver_app needs a matching German translation block added (~140 keys).

**Action required:** Add `de` to `Driver_app/lib/translations.ts` (all keys) and to the `Language` type + language picker in `Driver_app/contexts/LanguageContext.tsx` and `Driver_app/app/login.tsx`.

---

### 5.2 — Dashboard_SaaS: Entire Pages With No Translation (100% Hardcoded English)

These pages import `useLanguage` (or nothing) but render **all visible text as raw English strings**:

| Page | Key Hardcoded Strings |
|------|-----------------------|
| `DriverLogin.tsx` | "Driver Login", "Sign in to access your delivery routes", "Forgot password?", "Company Admin Login", all form labels |
| `DriverDashboard.tsx` | "Driver", "Vehicle:", "Logout", "Completed Today", "Pending", "Total Distance", "Today's Routes", "No routes assigned for today", "Upcoming Deliveries", "No deliveries scheduled" |
| `DriverResetPassword.tsx` | "Reset Password", "Check Your Email", "We've sent a password reset link to", "Back to Login", "Sending...", "Enter your email to receive a password reset link" |
| `AdminDashboard.tsx` | "Super Admin Dashboard", "Overview of all companies and subscriptions", all stat card labels, all table headers, "No companies found" |
| `AdminCodeManagement.tsx` | "Create New Company", "Company Management", "Add Company", all form labels (Company Name, Owner Full Name, Email, Password), all table headers, modal titles |
| `CompanyDetail.tsx` | "Back to Dashboard", "Company Details & Statistics", all field labels (Owner Email, Subscription Status, Plan, Trial End Date), all modal form labels, chart title |
| `ResetPassword.tsx` | "Set New Password", "Password Reset Successful", "Your password has been updated. Redirecting to login...", all form labels |

---

### 5.3 — Dashboard_SaaS: Pages Using `t.` But Still With Hardcoded Strings

These pages correctly use `t.keyName` for some text but leave other strings hardcoded in English:

#### `Layout.tsx` — Navigation Labels
```
Line 34: label: 'Dashboard'          → should be t.dashboard
Line 35: label: 'Code Management'    → missing key: t.codeManagement
Line 36: label: 'Plan Management'    → missing key: t.planManagement
Line 45: label: 'Workshop'           → missing key: t.workshop
Line 47: label: 'Customers'          → missing key: t.customers
Line 48: label: 'Staff'              → missing key: t.staff
Line 49: label: 'Communications'     → missing key: t.communications
Line 109: 'Logistics Control'        → missing key: t.logisticsControl
Line 126: 'Logistics Control'        → missing key: t.logisticsControl
Line 129: 'Super Administrator'      → missing key: t.superAdministrator
Line 133: 'Administrator'            → missing key: t.administrator
```

#### `Customers.tsx` — Entire customer section missing from translations
```
"Customers" heading              → missing key: t.customers
"Manage your customer database"  → missing key: t.customersSubtitle
"Add Customer"                   → missing key: t.addCustomer
"Search customers by name..."    → missing key: t.searchCustomers
"No customers found"             → missing key: t.noCustomersFound
"Edit Customer" / "Add Customer" → missing key: t.editCustomer / t.addCustomer
All form labels: Customer Name, Phone, Email, Address, Notes (partially overlap with existing keys)
Customer profile modal: "Total Orders", "Last Order", "Current Status", "Order History" → all missing
```

#### `StaffManagement.tsx` — Entire section missing from translations
```
Line 202: "Staff Management"                    → missing key: t.staffManagement
Line 203: "Manage workshop and office staff"    → missing key: t.staffSubtitle
Line 245: "No staff members yet"                → missing key: t.noStaffYet
Line 246: "Add your first staff member..."      → missing key: t.addFirstStaff
Line 352: "Workshop" / "Staff" / "Admin"        → missing keys: t.workshop / t.staff / t.adminRole
Form labels (Full Name, Email, Password, Role)  → partially overlap with existing keys
```

#### `Workshop.tsx` — Workshop stage labels and placeholders
```
Line 369: alt="Before"                                           → should be translated
Line 403: alt="After"                                            → should be translated
Line 446: placeholder="General notes about the cleaning..."      → missing key: t.workshopNotesPlaceholder
Line 459: placeholder="Any damage found or special care..."      → missing key: t.workshopDamagePlaceholder
Workshop stage names (received, washing, drying, ready)          → missing keys in translations
```

#### `Communications.tsx` — Almost entirely hardcoded
```
"Communications" heading
"Send messages and photos to your customers"
"Loading communication settings..."
"Webhook settings not configured"
"WhatsApp" / "Email" / "Photos" channel labels
"Single Message" / "Bulk Message" section titles
"Select Customer", "Phone Number", "Message" labels
All button texts, error messages, success messages
→ This entire page section is absent from the translations file
```

#### `Billing.tsx` — Several strings not in translations
```
"Available Plans"         → missing key: t.availablePlans
"/ month"                 → missing key: t.perMonth
"Setup Fee"               → missing key: t.setupFee
"Paid" / "Unpaid"         → missing keys: t.paid already exists, t.unpaid missing
"Current Subscription"    → missing key: t.currentSubscription
"Manage Subscription"     → missing key: t.manageSubscription
```

#### `Drivers.tsx` — Alert/confirm strings not translated
```
Line 134: alert('Driver updated but password reset email failed...')
Line 136: alert('A password reset email has been sent to the driver.')
Line 142: alert('Email and password are required for new drivers')
Line 188: alert('Driver updated/created successfully')
Line 209: confirm('Are you sure you want to delete this driver?')
Line 217: alert('Failed to delete driver')
```

#### `Login.tsx` — Forgot password / super admin mode
```
Line 146: "Reset Password" modal title  → missing key: t.resetPasswordTitle
Line 149: "Enter your email to receive a password reset link"  → missing key: t.forgotPasswordSubtitle
Line 239: "Forgot password?"  → missing key: t.forgotPassword
Line 251: "Create regular company account" / "Create super admin account instead"  → missing keys
```

---

### 5.4 — Dashboard_SaaS: Missing Order Status Keys

The actual order lifecycle used in `Orders.tsx` (line 235) is:
```
new → picked_up → at_workshop → washing → drying → ready → out_for_delivery → delivered
```

But the translation file only defines:
```
new, assigned, picked_up, in_cleaning, out_for_delivery, delivered, cancelled
```

**Missing status keys in ALL 5 languages (EN/TR/FR/DE/NL):**

| Key | EN value needed |
|-----|----------------|
| `at_workshop` | "At Workshop" *(atWorkshop key exists but maps to a display label, not status key)* |
| `washing` | "Washing" |
| `drying` | "Drying" |
| `ready` | "Ready for Delivery" |

> **Note:** `in_cleaning` is defined in translations but is **no longer a valid order status** in the DB (it was replaced by `washing`/`drying`/`ready`). It should be removed or reassigned.

---

### 5.5 — Driver App: Missing Keys per Language

The Driver_app `translations.ts` has ~140 keys defined for TR, EN, FR, NL. Comparing across locales:

| Key | TR | EN | FR | NL | DE |
|-----|----|----|----|----|-----|
| `dutch` | `'Flamanca'` | `'Dutch'` | `'Néerlandais'` | `'Nederlands'` | ❌ missing |
| **Entire `de` locale** | — | — | — | — | ❌ ALL 140 keys missing |

The `fr` locale also references `dutch: 'Néerlandais'` but has no `german` key — once DE is added to the picker, this key needs adding to all 5 locales.

---

### 5.6 — Summary: Keys to Add to Dashboard_SaaS Translations (All 5 Languages)

```
Navigation section:
  workshop, customers, staff, communications
  codeManagement, planManagement
  logisticsControl, superAdministrator, administrator

Order statuses:
  washing, drying, ready
  (remove or repurpose: in_cleaning)

Customers page:
  customersSubtitle, addCustomer, editCustomer, searchCustomers
  noCustomersFound, customerEmail, customerAddress, addFirstCustomer
  totalOrders (already exists), lastOrder, orderHistory, currentStatus

Staff Management page:
  staffManagement, staffSubtitle, addStaff, editStaff
  noStaffYet, addFirstStaff, staffName, staffRole, staffPassword
  adminRole (or repurpose existing keys)

Workshop page:
  workshopNotesPlaceholder, workshopDamagePlaceholder
  stageBefore, stageAfter
  washing, drying (overlap with order statuses above)

Driver pages:
  driverLogin, driverLoginSubtitle, forgotPassword, companyAdminLogin
  driverDashboardTitle, completedToday, todaysRoutes
  noRoutesToday, upcomingDeliveries, noDeliveriesScheduled, logout

Communications page:
  communicationsTitle, communicationsSubtitle
  whatsapp, emailChannel, photosChannel
  singleMessage, bulkMessage
  selectCustomer, sendMessage, messageSent
  filterByStatus, searchCustomers (overlap above)

Billing page:
  availablePlans, perMonth, setupFee, unpaid
  currentSubscription, manageSubscription, selectPlan

Login/Reset:
  forgotPassword, forgotPasswordSubtitle, resetPasswordTitle
  sendResetLink, checkYourEmail, resetLinkSent
```

---

### 5.7 — Summary: Keys to Add to Driver App Translations

1. **Add full `de` locale** to `Driver_app/lib/translations.ts` (copy EN ~140 keys, translate to German)
2. **Add `'de'` to Language type** in `Driver_app/contexts/LanguageContext.tsx`
3. **Add German option** to the language picker in `Driver_app/app/login.tsx`
4. **Add `german` key** to all 5 locale objects: `{ tr: 'Almanca', en: 'German', fr: 'Allemand', nl: 'Duits', de: 'Deutsch' }`

---

## 🔢 Work Estimate

| Item | Scope | Priority |
|------|-------|----------|
| Add DE locale to Driver_app | ~140 key translations | 🔴 HIGH |
| Add missing order status keys (washing/drying/ready) | 5 keys × 5 langs = 25 values | 🔴 HIGH |
| Wire up Layout.tsx nav items via `t.` | ~10 keys | 🟡 MEDIUM |
| Add Customers + Staff page i18n keys | ~30 keys × 5 langs | 🟡 MEDIUM |
| Full i18n for DriverLogin + DriverDashboard | ~20 keys × 5 langs | 🟡 MEDIUM |
| Full i18n for Admin pages (AdminDashboard, CompanyDetail, AdminCodeManagement) | ~60 keys × 5 langs | 🟢 LOW (admin-only) |
| Full i18n for Communications page | ~40 keys × 5 langs | 🟢 LOW |
| Remove obsolete `in_cleaning` status key | 1 key × 5 langs | 🟡 MEDIUM |

---

*Good night — see you in 3 hours! 🌙*
