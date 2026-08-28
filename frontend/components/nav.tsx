import Link from "next/link";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/breakouts", label: "Breakouts" },
  { href: "/search", label: "Search" },
];

export function Nav() {
  return (
    <nav className="flex items-center gap-4 text-sm">
      {LINKS.map((link) => (
        <Link key={link.href} href={link.href} className="hover:underline underline-offset-4">
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
