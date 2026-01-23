# Implementation Plan - Logic & Architecture Improvements

This plan addresses the requirement to introduce a **Company Admin** (Enterprise Admin) level, enable **Support Access** for Root Admins, and initially structure the **License Logic**.

## Goal
1.  **Company Admin**: Establish a user role linked directly to the `Company` that can manage the company and its tenants.
2.  **Support Access**: Allow Company Admins to grant temporary access to Root Admins for support purposes.
3.  **License Logic**: Enforce limits (Users, Files) at the Company level.

## User Review Required
> [!IMPORTANT]
> **Schema Change**: A new model `CompanyUser` will be created. Existing `Company` records might need manual assignment of an admin if they exist.
> **Permission Logic**: The `TenantFilterMixin` in `admin.py` will be updated to allow Company Admins to see all their Tenants.

## Proposed Changes

### 1. Data Models (`dms/models.py`)

#### [NEW] `CompanyUser`
Links a `User` to a `Company`.
- `company` (FK to Company)
- `user` (FK to User)
- `is_main_admin` (Bool, identifies the primary contact/admin)
- `role` (Choices: ADMIN, USER - default ADMIN for now as requested "Company Admin")

#### [MODIFY] `Company`
Add support access fields.
- `support_access_granted_until` (DateTimeField, nullable)
- `support_access_granted_by` (FK to User, nullable)

#### [MODIFY] `License` (Conceptual / Placeholder)
The user asked to "think about license logic".
Current `Company` model has:
- `license_max_mandanten`
- `license_max_users`
- `license_max_personnel_files`
We will keep these but ensure logic enforces them. We might add a validation method `check_limits()`.

### 2. Admin & Permissions (`dms/admin.py`)

#### [MODIFY] `BlindRootAdminMixin` & `TenantFilterMixin`
- Update logic:
    - If `request.user` is **Superuser**:
        - Limit access normally (Blind).
        - **EXCEPTION**: If `company.support_access_granted_until > now`, allow access to that Company's Tenants.
    - If `request.user` is **Company Admin**:
        - Allow access to ALL Tenants belonging to their Company.
        - Allow creating new Tenants (if limit not reached).

#### [MODIFY] `CompanyAdmin`
- Add inline for `CompanyUser` to manage admins.
- Add "Grant Support Access" action (visible only to Company Admin, or editable field).
- Add "Create Company" flow modification: When creating a Company via Root Admin, require an Admin Email. (Can be done via `save_model` or a custom Form).

### 3. Logic Implementation

- **Signal/Save**: When a `Company` is created, if an email is provided in a custom field (non-db), invite that user and make them `CompanyUser`.
- **Tenant Creation**: Check `company.license_mandanten_remaining` before creating.
- **User Creation**: Check `company.license_users_remaining`.
- **File Upload**: Check `company.license_personnel_files_remaining`.

## Verification Plan

### Manual Verification
1.  **Create Company**: Create a new Company via Admin, specifying an Admin Email.
2.  **Verify Admin**: Check if `CompanyUser` is created.
3.  **Company Admin Login**: Log in as the new Company Admin.
4.  **Manage Tenants**: Try to create a Tenant. Verify "Blind" aspect (can only see own).
5.  **Support Access**:
    - As Company Admin, set "Support Access" to active.
    - As Root Admin, try to view the Company's Tenants/Data.
6.  **License Limits**:
    - Reduce `license_max_mandanten` to 1.
    - Try to create a second tenant. Expect error/block.
