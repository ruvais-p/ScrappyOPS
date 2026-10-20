/* STEP 19 · stock release to HQ is now a supervisor job
   Already applied (migration perm_19_release_stock_supervisor). Do not run again.
   release_to_hq() now allows only roles 'supervisor' and 'hq' (before: 'warehouse' and 'hq').
   To undo: create or replace release_to_hq with  my_role() not in ('warehouse','hq')  in the first check.
   The warehouse dashboard shows the Release button only to the supervisor (and HQ). */
