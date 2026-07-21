-- ============================================================
-- JARVIS phase 1 — user schema (MSSQL 2022)
-- ใช้สร้างทั้ง jarvis (จริง) และ jarvis_test (ทดสอบ)
-- ส่งชื่อ DB ผ่านตัวแปร sqlcmd:  sqlcmd -v DB="jarvis_test" -i schema.sql
-- Thai-safe: NVARCHAR + Thai_CI_AS ; DATETIME2 ; UTC
-- ============================================================
IF DB_ID(N'$(DB)') IS NULL
    EXEC(N'CREATE DATABASE [$(DB)] COLLATE Thai_CI_AS');
GO
USE [$(DB)];
GO

IF OBJECT_ID('dbo.users', 'U') IS NULL
CREATE TABLE dbo.users (
    id             INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    username       NVARCHAR(50)  NOT NULL,
    password_hash  VARCHAR(255)  NOT NULL,            -- bcrypt = ASCII, VARCHAR พอ
    first_name     NVARCHAR(50)  NOT NULL,
    last_name      NVARCHAR(50)  NOT NULL,
    employee_id    NVARCHAR(20)  NOT NULL,
    email          NVARCHAR(100) NOT NULL,
    phone          NVARCHAR(20)  NULL,                -- optional
    role           NVARCHAR(20)  NOT NULL DEFAULT N'user',   -- 'user' | 'approver' | 'admin'
    is_active      BIT           NOT NULL DEFAULT 1,
    created_at     DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at     DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    last_login_at  DATETIME2(0)  NULL,

    CONSTRAINT UQ_users_username    UNIQUE (username),
    CONSTRAINT UQ_users_employee_id UNIQUE (employee_id),
    CONSTRAINT UQ_users_email       UNIQUE (email),
    CONSTRAINT CK_users_role        CHECK (role IN (N'user', N'approver', N'admin'))
);
GO
