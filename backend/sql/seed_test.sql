USE jarvis_test;
DELETE FROM dbo.users;
INSERT INTO dbo.users (username,password_hash,first_name,last_name,employee_id,email,phone,role) VALUES
(N'admin', '$2b$12$kzDhpuHfBJD/bpj9wbTfn.DSEyK6u/WubGVdzE.N0uURVVYiiSmpu', N'สมชาย', N'ผู้ดูแล', N'EMP001', N'admin@jarvis.com', N'090-111-1111', N'admin'),
(N'approver', '$2b$12$tghpJcML.nfV6t0xJ5rKVe271Xu3g3SJbmND0x91yQj4c.UzgwfIi', N'สมหญิง', N'หัวหน้า', N'EMP002', N'approver@jarvis.com', N'090-222-2222', N'approver'),
(N'user1', '$2b$12$b/9ouJonMFQ712eQQBoTYOqj0bXzZDjFsGborhkx6D8b3QByXRXde', N'สมศักดิ์', N'ช่าง', N'EMP003', N'user1@jarvis.com', N'090-333-3333', N'user'),
(N'user2', '$2b$12$gXqLhOD6w9ILr4gJqRfGueJvU.bN2H7fvh/v2SWzdCY5FUVpY/U8u', N'มานี', N'ใจดี', N'EMP004', N'user2@jarvis.com', NULL, N'user'),
(N'user3', '$2b$12$pIcO2IBpQSeQeBhl2n5pTuk6yQfcCqwPHj4M18Laes4Ah2qi3XhV6', N'ปิติ', N'ชูใจ', N'EMP005', N'user3@jarvis.com', NULL, N'user');
