import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

// Password input with a show/hide eye toggle. Drop-in replacement for a bare
// <input type="password"> — pass the same className/data-testid you'd use on
// the input; put any margin on wrapperClassName so the eye stays centered.
export function PasswordField({ className = "", testid, wrapperClassName = "", ...props }) {
  const [show, setShow] = useState(false);
  return (
    <div className={`relative ${wrapperClassName}`}>
      <input
        {...props}
        type={show ? "text" : "password"}
        data-testid={testid}
        className={`${className} pr-11`}
      />
      <button
        type="button"
        tabIndex={-1}
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "Hide password" : "Show password"}
        data-testid={testid ? `${testid}-toggle` : "password-toggle"}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-ayana-muted hover:text-ayana-text transition-colors"
      >
        {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  );
}

export default PasswordField;
