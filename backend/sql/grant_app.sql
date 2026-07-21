-- map SQL login jarvis_app เป็น user + ให้สิทธิ์อ่าน/เขียน ทั้ง 2 DB
USE jarvis_test;
IF USER_ID('jarvis_app') IS NULL CREATE USER jarvis_app FOR LOGIN jarvis_app;
ALTER ROLE db_datareader ADD MEMBER jarvis_app;
ALTER ROLE db_datawriter ADD MEMBER jarvis_app;
GO
USE jarvis;
IF USER_ID('jarvis_app') IS NULL CREATE USER jarvis_app FOR LOGIN jarvis_app;
ALTER ROLE db_datareader ADD MEMBER jarvis_app;
ALTER ROLE db_datawriter ADD MEMBER jarvis_app;
GO
