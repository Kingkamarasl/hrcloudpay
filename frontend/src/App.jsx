import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import AppLayout from './components/AppLayout';
import MarketingLayout from './components/MarketingLayout';
import ProtectedRoute from './components/ProtectedRoute';
const RoleRoute = ProtectedRoute;
import { KNOWLEDGE_MANAGER_ROLES } from './constants/roles';
import ErrorBoundary from './components/ErrorBoundary';
import { FeatureProvider } from './context/FeatureContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ToastProvider } from './context/ToastContext';
import { ThemeProvider } from './context/ThemeContext';
import Skeleton from './components/Skeleton';

// Lazy-loaded pages — code splitting for better initial load
const About = lazy(() => import('./pages/About'));
const Activate = lazy(() => import('./pages/Activate'));
const Attendance = lazy(() => import('./pages/Attendance'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Departments = lazy(() => import('./pages/Departments'));
const Employees = lazy(() => import('./pages/Employees'));
const EmployeeProfile = lazy(() => import('./pages/EmployeeProfile'));
const Home = lazy(() => import('./pages/Home'));
const Platform = lazy(() => import('./pages/Platform'));
const PayrollProduct = lazy(() => import('./pages/PayrollProduct'));
const HRProduct = lazy(() => import('./pages/HRProduct'));
const LeaveRequests = lazy(() => import('./pages/LeaveRequests'));
const LeaveAccrual = lazy(() => import('./pages/LeaveAccrual'));
const Login = lazy(() => import('./pages/Login'));
const Payroll = lazy(() => import('./pages/Payroll'));
const PayrollDashboard = lazy(() => import('./pages/PayrollDashboard'));
const PayrollSetup = lazy(() => import('./pages/PayrollSetup'));
const PayrollExtras = lazy(() => import('./pages/PayrollExtras'));
const Pricing = lazy(() => import('./pages/Pricing'));
const Register = lazy(() => import('./pages/Register'));
const ResetPassword = lazy(() => import('./pages/ResetPassword'));
const Team = lazy(() => import('./pages/Team'));
const PlatformAdmin = lazy(() => import('./pages/PlatformAdmin'));
const AuditLogs = lazy(() => import('./pages/AuditLogs'));
const Billing = lazy(() => import('./pages/Billing'));
const CompanySettings = lazy(() => import('./pages/CompanySettings'));
const Integrations = lazy(() => import('./pages/Integrations'));
const Compliance = lazy(() => import('./pages/Compliance'));
const StatutoryCompliance = lazy(() => import('./pages/StatutoryCompliance'));
const Workflows = lazy(() => import('./pages/Workflows'));
const RegionalOnboarding = lazy(() => import('./pages/RegionalOnboarding'));
const RequestTracking = lazy(() => import('./pages/RequestTracking'));
const Security = lazy(() => import('./pages/Security'));
const AIAssistant = lazy(() => import('./pages/AIAssistant'));
const KnowledgeCenter = lazy(() => import('./pages/KnowledgeCenter'));
const OperationsHub = lazy(() => import('./pages/OperationsHub'));
const SecurityCenter = lazy(() => import('./pages/SecurityCenter'));

function PlatformOnlyRoute({ children }) {
  const { user } = useAuth();
  if (!user?.is_staff && !user?.is_superuser) return <Navigate to="/dashboard" replace />;
  return children;
}

function PageLoader() {
  return <Skeleton />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>
            <FeatureProvider>
              <BrowserRouter>
                <Suspense fallback={<PageLoader />}>
                  <Routes>
                    <Route element={<MarketingLayout />}>
                      <Route path="/" element={<Home />} />
                      <Route path="/platform" element={<Platform />} />
                      <Route path="/payroll-product" element={<PayrollProduct />} />
                      <Route path="/hr" element={<HRProduct />} />
                      <Route path="/about" element={<About />} />
                      <Route path="/pricing" element={<Pricing />} />
                      <Route path="/security" element={<Security />} />
                    </Route>

                    <Route path="/login" element={<Login />} />
                    <Route path="/register" element={<Register />} />
{/* Public: a person who has just followed a reset link has no session,
    which is the whole point of the flow. */}
<Route path="/forgot-password" element={<ResetPassword />} />
<Route path="/reset-password/:uid/:token" element={<ResetPassword />} />
                    <Route path="/activate/:companyId/:token" element={<Activate />} />

                    <Route
                      element={
                        <ProtectedRoute>
                          <AppLayout />
                        </ProtectedRoute>
                      }
                    >
                      <Route path="/dashboard" element={<Dashboard />} />
                      <Route path="/security-center" element={<SecurityCenter />} />
                      <Route path="/ai" element={<AIAssistant />} />
                      <Route path="/knowledge" element={<RoleRoute roles={KNOWLEDGE_MANAGER_ROLES}><KnowledgeCenter /></RoleRoute>} />
                      <Route path="/employee-operations" element={<OperationsHub type="employee" />} />
                      <Route path="/payroll-operations" element={<OperationsHub type="payroll" />} />
                      <Route path="/workforce-operations" element={<OperationsHub type="leave" />} />
                      <Route path="/employees" element={<Employees />} />
                      <Route path="/employees/:id" element={<EmployeeProfile />} />
                      <Route path="/departments" element={<Departments />} />
                      <Route path="/payroll" element={<Payroll />} />
                      <Route path="/payroll-dashboard" element={<PayrollDashboard />} />
                      <Route path="/payroll-setup" element={<PayrollSetup />} />
                      <Route path="/payroll-extras" element={<PayrollExtras />} />
                      <Route path="/attendance" element={<Attendance />} />
                      <Route path="/leave" element={<LeaveRequests />} />
                      <Route path="/leave-accrual" element={<LeaveAccrual />} />
                      <Route path="/team" element={<Team />} />
                      <Route path="/request-tracking" element={<RequestTracking />} />
                      <Route path="/audit-logs" element={<AuditLogs />} />
                      <Route path="/billing" element={<Billing />} />
                      <Route path="/billing/success" element={<Billing />} />
                      <Route path="/company-settings" element={<CompanySettings />} />
                      <Route path="/integrations" element={<Integrations />} />
                      <Route path="/compliance" element={<Compliance />} />
                      <Route path="/statutory-compliance" element={<StatutoryCompliance />} />
                      <Route path="/workflows" element={<Workflows />} />
                      <Route path="/country-setup" element={<RegionalOnboarding />} />
                    </Route>

                    <Route
                      path="/platform-admin"
                      element={
                        <ProtectedRoute>
                          <PlatformOnlyRoute>
                            <PlatformAdmin />
                          </PlatformOnlyRoute>
                        </ProtectedRoute>
                      }
                    />

                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </Suspense>
              </BrowserRouter>
            </FeatureProvider>
          </AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
