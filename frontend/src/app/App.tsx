import { Loader2, ShieldOff } from "lucide-react";
import { lazy, Suspense, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/page";
import { useAuth } from "@/lib/auth";

const Landing = lazy(() => import("@/pages/Landing"));
const Login = lazy(() => import("@/pages/Login"));
const Register = lazy(() => import("@/pages/Register"));
const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
const ResetPassword = lazy(() => import("@/pages/ResetPassword"));
const AuthCallback = lazy(() => import("@/pages/AuthCallback"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Questions = lazy(() => import("@/pages/Questions"));
const Variants = lazy(() => import("@/pages/Variants"));
const Review = lazy(() => import("@/pages/Review"));
const Calibration = lazy(() => import("@/pages/Calibration"));
const Exposure = lazy(() => import("@/pages/Exposure"));
const Leaks = lazy(() => import("@/pages/Leaks"));
const Assembler = lazy(() => import("@/pages/Assembler"));
const Reports = lazy(() => import("@/pages/Reports"));
const Settings = lazy(() => import("@/pages/Settings"));
const CandidateHome = lazy(() => import("@/pages/CandidateHome"));
const Assessment = lazy(() => import("@/pages/Assessment"));

function Spinner() {
  return (
    <div className="grid h-full min-h-[50vh] place-items-center text-fg-subtle" role="status" aria-label="Loading">
      <Loader2 className="size-5 animate-spin" />
    </div>
  );
}

function RequireAuth({ children, perm }: { children: ReactNode; perm?: string }) {
  const { user, loading, can } = useAuth();
  const loc = useLocation();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (perm && !can(perm)) {
    return (
      <EmptyState icon={<ShieldOff />} title="You don't have access to this area"
        description={`Your role (${user.role_label}) lacks the '${perm}' permission. Access is enforced by the API as well.`}
        action={<Button asChild variant="secondary"><Link to={user.role === "candidate" ? "/assessment" : "/dashboard"}>Go to your workspace</Link></Button>} />
    );
  }
  return <>{children}</>;
}

function Home() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={user.role === "candidate" ? "/assessment" : "/dashboard"} replace />;
}

const staff: [string, string, ReactNode][] = [
  ["/dashboard", "dashboard.read", <Dashboard />],
  ["/questions", "questions.read", <Questions />],
  ["/variants", "questions.read", <Variants />],
  ["/review", "questions.read", <Review />],
  ["/calibration", "calibration.read", <Calibration />],
  ["/exposure", "exposure.read", <Exposure />],
  ["/leaks", "leaks.read", <Leaks />],
  ["/assembler", "assembly.read", <Assembler />],
  ["/reports", "reports.read", <Reports />],
  ["/settings", "dashboard.read", <Settings />],
];

export function App() {
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/app" element={<Home />} />
        <Route path="/assessment" element={<RequireAuth perm="assessment.take"><CandidateHome /></RequireAuth>} />
        <Route path="/assessment/:formId" element={<RequireAuth perm="assessment.take"><Assessment /></RequireAuth>} />
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          {staff.map(([path, perm, el]) => (
            <Route key={path} path={path} element={<RequireAuth perm={perm}><Suspense fallback={<Spinner />}>{el}</Suspense></RequireAuth>} />
          ))}
        </Route>
        <Route path="*" element={
          <div className="grid h-full place-items-center">
            <EmptyState title="Page not found" description="The page you requested does not exist."
              action={<Button asChild variant="primary"><Link to="/app">Back to workspace</Link></Button>} />
          </div>} />
      </Routes>
    </Suspense>
  );
}
