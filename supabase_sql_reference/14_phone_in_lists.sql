/* =====================================================================
   STEP 14 · customer phone for collectors, and name/phone/location for the warehouse
   Already applied (migration lead_14_phone_in_lists). Do not run again.
     - my_leads() (collector) now also returns the customer's phone
     - wh_pickups() (warehouse and HQ) now also returns customer name, phone, latitude, longitude
   Rows stay limited to the user's own franchise, as before.
   ===================================================================== */
-- see the applied migration for the full function bodies (my_leads and wh_pickups with the extra columns)
