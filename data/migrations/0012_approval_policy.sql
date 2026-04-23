ALTER TABLE approvals ADD COLUMN category TEXT;
ALTER TABLE approvals ADD COLUMN permission_classes_json TEXT NOT NULL DEFAULT '[]';
