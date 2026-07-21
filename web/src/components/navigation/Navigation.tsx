import { NavLink } from "react-router-dom";

const links = [
  ["/", "Status"],
  ["/search", "Search"],
  ["/library", "Library"],
  ["/fit-check", "Fit Check"],
] as const;

export function Navigation() {
  return (
    <nav aria-label="Primary navigation">
      <ul className="navigation">
        {links.map(([to, label]) => (
          <li key={to}>
            <NavLink end={to === "/"} to={to}>
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
