/* =====================================================================
   STEP 16 · one login per person ("newest login wins")
   Already applied (migration sec_16_single_session). Do not run again.

   How it works
     - trigger one_session_per_user on auth.sessions: when someone logs in, their other
       sessions are deleted (the old device can no longer refresh its login).
     - session_valid(): true while this login's session still exists.
     - my_role(), my_franchise(), my_leads(), _my_bill(), end_route() now check session_valid(),
       so an old device loses access at once instead of when its token expires.
     - the dashboards call session_valid() every 20 seconds and sign the old device out.

   To switch the rule off again (nothing else needs to change):
     drop trigger if exists one_session_per_user on auth.sessions;
   ===================================================================== */
