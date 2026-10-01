CREATE DATABASE IF NOT EXISTS startup_labbook
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE startup_labbook;

CREATE TABLE IF NOT EXISTS admins (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(190) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_admin_active (active)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS employees (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    employee_code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(190) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    designation VARCHAR(120) NOT NULL,
    department VARCHAR(120) NOT NULL,
    phone VARCHAR(30) NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_employee_active (active),
    INDEX idx_employee_department (department),
    INDEX idx_employee_designation (designation)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS attendance_sessions (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    attendance_date DATE NOT NULL,
    code CHAR(6) NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_attendance_session_date (attendance_date),
    INDEX idx_attendance_session_expiry (expires_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS attendance (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    employee_id INT UNSIGNED NOT NULL,
    attendance_date DATE NOT NULL,
    check_in DATETIME NULL,
    check_out DATETIME NULL,
    status ENUM('Present','Late') NOT NULL DEFAULT 'Present',
    session_id INT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_attendance_employee FOREIGN KEY (employee_id) REFERENCES employees(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_attendance_session FOREIGN KEY (session_id) REFERENCES attendance_sessions(id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT uq_employee_attendance_date UNIQUE (employee_id, attendance_date),
    INDEX idx_attendance_date (attendance_date),
    INDEX idx_attendance_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS daily_work (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    employee_id INT UNSIGNED NOT NULL,
    work_date DATE NOT NULL,
    work_title VARCHAR(180) NOT NULL,
    work_description TEXT NOT NULL,
    progress TINYINT UNSIGNED NOT NULL DEFAULT 0,
    status ENUM('Not Started','In Progress','Completed') NOT NULL DEFAULT 'Not Started',
    blockers TEXT NULL,
    tomorrow_plan TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_work_employee FOREIGN KEY (employee_id) REFERENCES employees(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT uq_employee_work_date UNIQUE (employee_id, work_date),
    INDEX idx_work_date (work_date),
    INDEX idx_work_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS meeting_notes (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    note_date DATE NOT NULL,
    title VARCHAR(180) NOT NULL,
    discussion TEXT NOT NULL,
    decisions TEXT NULL,
    action_items TEXT NULL,
    created_by INT UNSIGNED NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_notes_admin FOREIGN KEY (created_by) REFERENCES admins(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    INDEX idx_notes_date (note_date)
) ENGINE=InnoDB;
