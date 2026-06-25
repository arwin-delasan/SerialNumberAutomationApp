^XA
^MMT
^PW583
^LL224
^LS0

; --- Top-left text (VAR_A) ---
^FO70,18
^A0N,30,30
^FD{VAR_A}^FS

; --- Top-middle text (VAR_A, duplicate) ---
^FO270,18
^A0N,30,30
^FD{VAR_A}^FS

; --- Top-right text (VAR_B) ---
^FO485,24
^A0N,26,26
^FD{VAR_B}^FS

; --- Barcode 1 (encodes VAR_A) ---
^FO20,62
^BY2,2,53
^BCN,53,N,N,N
^FD{VAR_A}^FS

^FO70,120
^A0N,32,32
^FD{VAR_A}^FS

--- Barcode 2 (encodes VAR_A) ---
^FO250,66
^BY2,3,58
^BCN,58,N,N,N
^FD{VAR_A}^FS
 
^FO270,125
^A0N,32,32
^FD{VAR_A}^FS

; --- Middle-right text (VAR_B, duplicate) ---
^FO485,104
^A0N,26,26
^FD{VAR_B}^FS

; --- Bottom-right text (VAR_B, duplicate) ---
^FO485,160
^A0N,26,26
^FD{VAR_B}^FS

^XZ