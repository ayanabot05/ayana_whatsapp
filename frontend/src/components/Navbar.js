
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Menu } from "lucide-react";
import { Logo } from "@/components/Logo";
import { useState } from "react";

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const closeMenu = () => setOpen(false);

  const handleLogout = () => {
    logout();
    navigate("/");
    setOpen(false);
  };

  return (
    <header className="sticky top-0 z-50 backdrop-blur-xl bg-ayana-bg/70 border-b border-ayana-line/60">
      <div className="max-w-7xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between">

        {/* Logo */}
        <Link
          to="/"
          data-testid="nav-logo"
          className="flex items-center gap-2 group"
          onClick={closeMenu}
        >
          <Logo size={36} />
        </Link>

        {/* Desktop Navigation */}
        <nav className="hidden md:flex items-center gap-8 text-sm text-ayana-secondary">

          <a
            href="/#how"
            className="hover:text-ayana-text transition-colors duration-200"
          >
            How it works
          </a>

          <a
            href="/#what-they-see"
            className="hover:text-ayana-text transition-colors duration-200"
          >
            What parents see
          </a>

          <a
            href="/#safety"
            className="hover:text-ayana-text transition-colors duration-200"
          >
            Safety
          </a>

          <a
            href="/#trust"
            className="hover:text-ayana-text transition-colors duration-200"
          >
            Our promise
          </a>

          <a
            href="/#pricing"
            className="hover:text-ayana-text transition-colors duration-200"
          >
            Pricing
          </a>

          <a
            href="/#faq"
            className="hover:text-ayana-text transition-colors duration-200"
          >
            FAQ
          </a>

        </nav>

        {/* Desktop Auth */}
        <div className="hidden md:flex items-center gap-3">
          {user ? (
            <>
              {user.role === "admin" && (
                <Link
                  to="/admin"
                  data-testid="nav-admin"
                  className="text-sm text-ayana-secondary hover:text-ayana-text transition-colors"
                >
                  Admin
                </Link>
              )}

              <Link
                to="/dashboard"
                data-testid="nav-dashboard"
                className="text-sm font-medium text-ayana-text hover:text-ayana-primary transition-colors"
              >
                Dashboard
              </Link>

              <button
                data-testid="nav-logout"
                onClick={handleLogout}
                className="text-sm text-ayana-secondary hover:text-ayana-accent transition-colors"
              >
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link
                to="/login"
                data-testid="nav-login"
                className="text-sm font-medium text-ayana-text hover:text-ayana-primary transition-colors"
              >
                Log in
              </Link>

              <Link
                to="/signup"
                data-testid="nav-signup"
                className="text-sm font-medium px-5 py-2.5 rounded-full bg-ayana-primary text-white hover:bg-ayana-primary-hover transition-colors duration-200"
              >
                Get started
              </Link>
            </>
          )}
        </div>

        {/* Mobile Menu Button */}
        <button
          className="md:hidden text-ayana-text"
          onClick={() => setOpen(!open)}
          data-testid="nav-mobile-toggle"
          aria-label="Menu"
          aria-expanded={open}
        >
          <Menu className="w-6 h-6" strokeWidth={1.5} />
        </button>
      </div>

      {/* Mobile Navigation */}
      {open && (
        <div className="md:hidden border-t border-ayana-line/60 bg-ayana-bg px-5 py-4 flex flex-col gap-3 text-sm">

          <a
            href="/#how"
            onClick={closeMenu}
            className="hover:text-ayana-text transition-colors"
          >
            How it works
          </a>

          <a
            href="/#what-they-see"
            onClick={closeMenu}
            className="hover:text-ayana-text transition-colors"
          >
            What parents see
          </a>

          <a
            href="/#safety"
            onClick={closeMenu}
            className="hover:text-ayana-text transition-colors"
          >
            Safety
          </a>

          <a
            href="/#trust"
            onClick={closeMenu}
            className="hover:text-ayana-text transition-colors"
          >
            Our promise
          </a>

          <a
            href="/#pricing"
            onClick={closeMenu}
            className="hover:text-ayana-text transition-colors"
          >
            Pricing
          </a>

          <a
            href="/#faq"
            onClick={closeMenu}
            className="hover:text-ayana-text transition-colors"
          >
            FAQ
          </a>

          <div className="border-t border-ayana-line/60 pt-3 mt-1">
            {user ? (
              <div className="flex flex-col gap-3">
                {user.role === "admin" && (
                  <Link
                    to="/admin"
                    onClick={closeMenu}
                    className="text-ayana-secondary hover:text-ayana-text"
                  >
                    Admin
                  </Link>
                )}

                <Link
                  to="/dashboard"
                  onClick={closeMenu}
                  className="font-medium text-ayana-text"
                >
                  Dashboard
                </Link>

                <button
                  onClick={handleLogout}
                  className="text-left text-ayana-accent"
                >
                  Sign out
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <Link
                  to="/login"
                  onClick={closeMenu}
                  className="text-ayana-text"
                >
                  Log in
                </Link>

                <Link
                  to="/signup"
                  onClick={closeMenu}
                  className="font-medium text-ayana-primary"
                >
                  Get started
                </Link>
              </div>
            )}
          </div>
        </div>
      )}
    </header>
  );
}

