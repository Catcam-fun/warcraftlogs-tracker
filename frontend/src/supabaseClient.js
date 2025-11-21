import { createClient } from '@supabase/supabase-js'

const supabaseUrl = 'REDACTED'
const supabaseAnonKey = 'REDACTED'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)