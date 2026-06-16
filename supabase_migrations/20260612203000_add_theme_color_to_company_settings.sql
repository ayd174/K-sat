-- Migration: Add theme_color column to company_settings
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS theme_color text DEFAULT 'blue';
