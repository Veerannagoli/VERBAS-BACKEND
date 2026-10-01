-- VERBAS Employee Management
-- SAFE EMPLOYEE-DATA RESET
--
-- This removes employee accounts and their dependent attendance/work records.
-- It intentionally keeps:
--   1) admin accounts
--   2) meeting notes
--
-- BACK UP THE DATABASE BEFORE RUNNING THIS SCRIPT.
-- Run against the configured MYSQL_DB database only.

START TRANSACTION;

DELETE FROM attendance;
DELETE FROM daily_work;
DELETE FROM employees;
DELETE FROM attendance_sessions;

COMMIT;

-- Verification:
SELECT COUNT(*) AS employees_remaining FROM employees;
SELECT COUNT(*) AS attendance_remaining FROM attendance;
SELECT COUNT(*) AS work_records_remaining FROM daily_work;
SELECT COUNT(*) AS attendance_codes_remaining FROM attendance_sessions;
SELECT COUNT(*) AS admins_kept FROM admins;
SELECT COUNT(*) AS meeting_notes_kept FROM meeting_notes;
