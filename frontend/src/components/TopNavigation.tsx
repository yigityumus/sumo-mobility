import { cn } from "../lib/utils";
import ModeToggle from "./ModeToggle";

type NavigationItem = "home" | "analytics" | "documentation";

type TopNavigationProps = {
  active?: NavigationItem;
  onHome: () => void;
  onAnalytics: () => void;
  onDocumentation: () => void;
  className?: string;
};

export default function TopNavigation({ active, onHome, onAnalytics, onDocumentation, className }: TopNavigationProps) {
  const items: Array<{ id: NavigationItem; label: string; onClick: () => void }> = [
    { id: "home", label: "Home", onClick: onHome },
    { id: "analytics", label: "Analytics", onClick: onAnalytics },
    { id: "documentation", label: "Documentation", onClick: onDocumentation },
  ];

  return (
    <nav aria-label="Primary navigation" className={cn("flex items-center justify-end gap-5", className)}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          aria-current={active === item.id ? "page" : undefined}
          onClick={item.onClick}
          className={cn(
            "origin-center text-sm text-muted-foreground underline-offset-4 transition-all duration-150 hover:scale-110 hover:font-bold hover:text-foreground hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            active === item.id && "font-semibold text-foreground underline",
          )}
        >
          {item.label}
        </button>
      ))}
      <ModeToggle />
    </nav>
  );
}
