/* =====================================================================
   STEP 18 · branded invoice + WhatsApp message
   Already applied (migrations bill_18_whatsapp_message, 18b, 18c). Do not run again.

   - Edge function bill-pdf (deployed v7): new one-page invoice design. Source saved in warehouse_sql/bill-pdf/
       index.ts   the function (unchanged logic, adds franchise + customer phone)
       invoice.ts the invoice drawing (pdf-lib, Helvetica)
     The badge image is the file bill-badge.png on the Scrappy site (scrappy_app/bill-badge.png). The function fetches it,
     checks its length and checksum, and if it is missing the bill is drawn with a text badge. It never blocks a bill.
   - bill_whatsapp(): new message text (first name, bill no, weight, amount to receive). The app adds the PDF link,
     the collector's name and the brand line.
   - bill_pdf_test_key in app_secrets is NULL again (test mode off).
   ===================================================================== */
