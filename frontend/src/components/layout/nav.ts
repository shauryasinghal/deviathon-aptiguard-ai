import {
  Activity,
  BarChart3,
  Boxes,
  FileText,
  FlaskConical,
  Gauge,
  LayoutGrid,
  ListChecks,
  Radar,
  Settings,
  ShieldAlert,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

export type NavItem = { to: string; label: string; icon: LucideIcon; perm: string; badgeKey?: "review" | "alerts" };
export type NavGroup = { label: string; items: NavItem[] };

export const NAV: NavGroup[] = [
  { label: "Overview", items: [{ to: "/dashboard", label: "Command Center", icon: Gauge, perm: "dashboard.read" }] },
  {
    label: "Content",
    items: [
      { to: "/questions", label: "Question Bank", icon: LayoutGrid, perm: "questions.read" },
      { to: "/variants", label: "AI Variant Studio", icon: Sparkles, perm: "questions.read" },
      { to: "/review", label: "Reviewer Workspace", icon: ListChecks, perm: "questions.read", badgeKey: "review" },
    ],
  },
  {
    label: "Integrity",
    items: [
      { to: "/calibration", label: "Calibration Lab", icon: FlaskConical, perm: "calibration.read" },
      { to: "/exposure", label: "Exposure Intelligence", icon: Radar, perm: "exposure.read" },
      { to: "/leaks", label: "Leak Detection", icon: ShieldAlert, perm: "leaks.read", badgeKey: "alerts" },
    ],
  },
  { label: "Delivery", items: [{ to: "/assembler", label: "Test Assembler", icon: Boxes, perm: "assembly.read" }] },
  {
    label: "Governance",
    items: [
      { to: "/reports", label: "Analytics & Reports", icon: BarChart3, perm: "reports.read" },
      { to: "/settings", label: "Settings & Audit", icon: Settings, perm: "dashboard.read" },
    ],
  },
];

export const ROUTE_TITLES: Record<string, string> = {
  dashboard: "Command Center", questions: "Question Bank", variants: "AI Variant Studio", review: "Reviewer Workspace",
  calibration: "Calibration Lab", exposure: "Exposure Intelligence", leaks: "Leak Detection", assembler: "Test Assembler",
  reports: "Analytics & Reports", settings: "Settings & Audit", assessment: "Assessment",
};

export const ICONS = { Activity, FileText };
