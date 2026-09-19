;;; acadmcp.lsp - support library for the AutoCAD MCP server.
;;;
;;; Loaded once per drawing session. Provides:
;;;   acadmcp:job     run an expression, write {"ok":..,"result":..} as JSON
;;;   acadmcp:emit    stream any LISP value to an open file as ASCII-safe JSON
;;;   acadmcp:ss      build a selection set from a list of handles
;;;   acadmcp:handles list the handles in a selection set
;;;
;;; Everything is written incrementally to the output file so that very large
;;; results (thousands of entities) never build one enormous LISP string.

(vl-load-com)

;; --------------------------------------------------------------------------
;; number / string formatting
;; --------------------------------------------------------------------------

(defun acadmcp:hex4 (n / h s)
  (setq h "0123456789abcdef" s "")
  (repeat 4
    (setq s (strcat (substr h (1+ (rem n 16)) 1) s))
    (setq n (fix (/ n 16)))
  )
  s
)

(defun acadmcp:num (v / s)
  (setq s (rtos v 2 12))
  ;; DIMZIN can suppress the leading zero; JSON will not accept ".5"
  (cond
    ((= (substr s 1 1) ".") (setq s (strcat "0" s)))
    ((= (substr s 1 2) "-.") (setq s (strcat "-0" (substr s 2))))
  )
  (if (or (= s "") (= s "-")) "0" s)
)

(defun acadmcp:estr (f s / i n c a)
  ;; write s to file f as a JSON string, escaping everything non-ASCII
  (princ "\"" f)
  (setq i 1 n (strlen s))
  (while (<= i n)
    (setq c (substr s i 1) a (ascii c))
    (cond
      ((= c "\\") (princ "\\\\" f))
      ((= c "\"") (princ "\\\"" f))
      ((= a 10) (princ "\\n" f))
      ((= a 13) (princ "\\r" f))
      ((= a 9) (princ "\\t" f))
      ((or (< a 32) (> a 126)) (princ (strcat "\\u" (acadmcp:hex4 a)) f))
      (t (princ c f))
    )
    (setq i (1+ i))
  )
  (princ "\"" f)
)

;; --------------------------------------------------------------------------
;; entity identity
;; --------------------------------------------------------------------------

(defun acadmcp:hnd (e / d)
  (if (and e (setq d (entget e))) (cdr (assoc 5 d)) nil)
)

(defun acadmcp:vhnd (o / r)
  (setq r (vl-catch-all-apply 'vla-get-Handle (list o)))
  (if (vl-catch-all-error-p r) nil r)
)

(defun acadmcp:handles (ss / i out)
  (setq i 0 out nil)
  (if ss
    (repeat (sslength ss)
      (setq out (cons (acadmcp:hnd (ssname ss i)) out) i (1+ i))
    )
  )
  (reverse out)
)

(defun acadmcp:ss (handles / ss e)
  ;; list of handle strings -> pickset (nil if none resolved)
  (setq ss (ssadd))
  (foreach h handles
    (if (and h (setq e (handent h))) (ssadd e ss))
  )
  (if (> (sslength ss) 0) ss nil)
)

(defun acadmcp:since (before / e out)
  ;; handles of everything created after entity `before` (nil = whole drawing)
  (setq out nil)
  (setq e (if before (entnext before) (entnext)))
  (while e
    (setq out (cons (acadmcp:hnd e) out))
    (setq e (entnext e))
  )
  (reverse out)
)

(defun acadmcp:capture (amx-cfn / amx-cb amx-cr)
  ;; run fn, return (value (handles it created))
  ;; NOTE: locals are prefixed because AutoLISP is dynamically scoped - the
  ;; caller's code runs inside our binding, so a plain (setq b ...) in their
  ;; expression would overwrite ours.
  (setq amx-cb (entlast))
  (setq amx-cr (apply amx-cfn nil))
  (list amx-cr (acadmcp:since amx-cb))
)

;; --------------------------------------------------------------------------
;; JSON emitter
;; --------------------------------------------------------------------------

(defun acadmcp:emit (f v / first tail r)
  (cond
    ((null v) (princ "null" f))
    ((eq v t) (princ "true" f))
    ((= (type v) 'str) (acadmcp:estr f v))
    ((= (type v) 'int) (princ (itoa v) f))
    ((= (type v) 'real) (princ (acadmcp:num v) f))
    ((= (type v) 'ename) (acadmcp:estr f (strcat "#" (acadmcp:hnd v))))
    ((= (type v) 'pickset) (acadmcp:emit f (acadmcp:handles v)))
    ((= (type v) 'sym) (acadmcp:estr f (vl-symbol-name v)))
    ((= (type v) 'subr) (acadmcp:estr f "<subr>"))
    ((= (type v) 'file) (acadmcp:estr f "<file>"))
    ((= (type v) 'vla-object)
     (setq r (acadmcp:vhnd v))
     (if r (acadmcp:estr f (strcat "#" r)) (acadmcp:estr f "<vla-object>"))
    )
    ((= (type v) 'variant) (acadmcp:emit f (vlax-variant-value v)))
    ((= (type v) 'safearray) (acadmcp:emit f (vlax-safearray->list v)))
    ((listp v)
     (setq tail (cdr v))
     (if (and tail (not (listp tail)))
       (progn                                  ; dotted pair -> 2 element array
         (princ "[" f)
         (acadmcp:emit f (car v))
         (princ "," f)
         (acadmcp:emit f tail)
         (princ "]" f)
       )
       (progn
         (princ "[" f)
         (setq first t)
         (foreach item v
           (if first (setq first nil) (princ "," f))
           (acadmcp:emit f item)
         )
         (princ "]" f)
       )
     )
    )
    (t (acadmcp:estr f (vl-princ-to-string v)))
  )
  v
)

;; --------------------------------------------------------------------------
;; system variable save / restore around command driving
;; --------------------------------------------------------------------------

(defun acadmcp:pushvars (quiet / saved)
  (setq saved nil)
  (if quiet
    (foreach pair '(("CMDECHO" . 0) ("FILEDIA" . 0) ("ATTDIA" . 0)
                    ("ATTREQ" . 0) ("EXPERT" . 5) ("OSMODE" . 0)
                    ("NOMUTT" . 1) ("CMDDIA" . 0))
      (setq saved (cons (cons (car pair) (getvar (car pair))) saved))
      (vl-catch-all-apply 'setvar (list (car pair) (cdr pair)))
    )
  )
  saved
)

(defun acadmcp:popvars (saved)
  (foreach pair saved
    (vl-catch-all-apply 'setvar (list (car pair) (cdr pair)))
  )
  nil
)

;; --------------------------------------------------------------------------
;; job runner
;; --------------------------------------------------------------------------

(defun acadmcp:wrfail (out msg / f)
  (setq f (open out "w"))
  (if f
    (progn
      (princ "{\"ok\":false,\"error\":" f)
      (acadmcp:estr f (if (= (type msg) 'str) msg (vl-princ-to-string msg)))
      (princ "}" f)
      (close f)
    )
  )
  nil
)

;; IMPORTANT - AutoLISP is dynamically scoped.  The caller's expression runs
;; inside this function's bindings, so a plain (setq out ...) in their code
;; would silently overwrite our `out` and we would later try to open a list as
;; a file name.  Every local here is therefore prefixed, and the ones we need
;; after the call are kept in acadmcp:* globals as well.
(defun acadmcp:job (amx-out amx-fn amx-quiet / amx-res amx-f)
  (setq acadmcp:*out* amx-out
        acadmcp:*done* nil
        acadmcp:*saved* (acadmcp:pushvars amx-quiet)
        acadmcp:*olderr* *error*)

  (defun *error* (msg)
    (acadmcp:popvars acadmcp:*saved*)
    (setq *error* acadmcp:*olderr*)
    (if (not acadmcp:*done*)
      (progn
        (setq acadmcp:*done* t)
        (acadmcp:wrfail acadmcp:*out* msg)
      )
    )
    (princ)
  )

  (setq amx-res (vl-catch-all-apply amx-fn nil))
  (acadmcp:popvars acadmcp:*saved*)
  (setq *error* acadmcp:*olderr*)

  (if (not acadmcp:*done*)
    (progn
      (setq acadmcp:*done* t)
      (if (vl-catch-all-error-p amx-res)
        (acadmcp:wrfail acadmcp:*out* (vl-catch-all-error-message amx-res))
        (progn
          (setq amx-f (open acadmcp:*out* "w"))
          (if amx-f
            (progn
              (princ "{\"ok\":true,\"result\":" amx-f)
              (acadmcp:emit amx-f amx-res)
              (princ "}" amx-f)
              (close amx-f)
            )
          )
        )
      )
    )
  )
  (princ)
)

(setq acadmcp:version "1.0")
(princ)
