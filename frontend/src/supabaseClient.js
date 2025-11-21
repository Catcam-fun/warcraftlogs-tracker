import { createClient } from '@supabase/supabase-js'

const supabaseUrl = 'https://eckershozscyedwfswsy.supabase.co'
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVja2Vyc2hvenNjeWVkd2Zzd3N5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM2NjM5MTEsImV4cCI6MjA3OTIzOTkxMX0.F1YkqGeJiYWte_EOW78DjNmqegWwy6TUaDE48LsA3HM'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)