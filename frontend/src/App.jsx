import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import { lazy, Suspense } from 'react';
import AppLayout from './components/AppLayout';
import MarketingLayout from './components/MarketingLayout';
import ProtectedRoute from './components/ProtectedRoute';
const RoleRoute = ProtectedRoute;
import { KNOWLEDGE_MANAGER_ROLES, DRAFT_MANAGER_ROLES } from './constants/roles';
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
const AttendanceGrid = lazy(() => import('./pages/AttendanceGrid'));
const Biometrics = lazy(() => import('./pages/Biometrics'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const EmployeeDashboard = lazy(() => import('./pages/EmployeeDashboard'));
const EmployeeMyProfile = lazy(() => import('./pages/EmployeeSelfService').then((m) => ({ default: m.EmployeeMyProfile })));
const EmployeeMyPayslips = lazy(() => import('./pages/EmployeeSelfService').then((m) => ({ default: m.EmployeeMyPayslips })));
const EmployeeMyAttendance = lazy(() => import('./pages/EmployeeSelfService').then((m) => ({ default: m.EmployeeMyAttendance })));
const EmployeeMyLeave = lazy(() => import('./pages/EmployeeSelfService').then((m) => ({ default: m.EmployeeMyLeave })));
const EmployeeMyDocuments = lazy(() => import('./pages/EmployeeSelfService').then((m) => ({ default: m.EmployeeMyDocuments })));
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
const AIDrafts = lazy(() => import('./pages/AIDrafts'));
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
const LegalPage = lazy(() => import('./pages/LegalPage'));
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

function DashboardRoute() {
  const { user } = useAuth();
  return user?.role === 'employee' ? <EmployeeDashboard /> : <Dashboard />;
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
          <Route path="/terms" element={<LegalPage slug="terms" />} />
          <Route path="/privacy" element={<LegalPage slug="privacy" />} />
          <Route path="/refund-policy" element={<LegalPage slug="refund-policy" />} />
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
                      <Route path="/dashboard" element={<DashboardRoute />} />
                      <Route path="/my-workspace" element={<RoleRoute roles={['employee']}><EmployeeDashboard /></RoleRoute>} />
                      <Route path="/my-profile" element={<RoleRoute roles={['employee']}><EmployeeMyProfile /></RoleRoute>} />
                      <Route path="/my-payslips" element={<RoleRoute roles={['employee']}><EmployeeMyPayslips /></RoleRoute>} />
                      <Route path="/my-attendance" element={<RoleRoute roles={['employee']}><EmployeeMyAttendance /></RoleRoute>} />
                      <Route path="/my-leave" element={<RoleRoute roles={['employee']}><EmployeeMyLeave /></RoleRoute>} />
                      <Route path="/my-documents" element={<RoleRoute roles={['employee']}><EmployeeMyDocuments /></RoleRoute>} />
                      <Route path="/security-center" element={<RoleRoute roles={['owner','admin']}><SecurityCenter /></RoleRoute>} />
                      <Route path="/ai" element={<RoleRoute roles={['owner','admin','hr','finance','department_manager']}><AIAssistant /></RoleRoute>} />
                      <Route path="/ai-drafts" element={<RoleRoute roles={DRAFT_MANAGER_ROLES}><AIDrafts /></RoleRoute>} />
                        <Route path="/knowledge" element={<RoleRoute roles={KNOWLEDGE_MANAGER_ROLES}><KnowledgeCenter /></RoleRoute>} />
                      <Route path="/employee-operations" element={<RoleRoute roles={['owner','admin','hr','department_manager']}><OperationsHub type="employee" /></RoleRoute>} />
                      <Route path="/payroll-operations" element={<RoleRoute roles={['owner','admin','finance']}><OperationsHub type="payroll" /></RoleRoute>} />
                      <Route path="/workforce-operations" element={<RoleRoute roles={['owner','admin','hr','department_manager']}><OperationsHub type="leave" /></RoleRoute>} />
                      <Route path="/employees" element={<RoleRoute roles={['owner','admin','hr','department_manager']}><Employees /></RoleRoute>} />
                      <Route path="/employees/:id" element={<RoleRoute roles={['owner','admin','hr','department_manager']}><EmployeeProfile /></RoleRoute>} />
                      <Route path="/departments" element={<RoleRoute roles={['owner','admin','hr','department_manager']}><Departments /></RoleRoute>} />
                      <Route path="/payroll" element={<RoleRoute roles={['owner','admin','finance']}><Payroll /></RoleRoute>} />
                      <Route path="/payroll-dashboard" element={<RoleRoute roles={['owner','admin','finance']}><PayrollDashboard /></RoleRoute>} />
                      <Route path="/payroll-setup" element={<RoleRoute roles={['owner','admin','finance']}><PayrollSetup /></RoleRoute>} />
                      <Route path="/payroll-extras" element={<RoleRoute roles={['owner','admin','finance']}><PayrollExtras /></RoleRoute>} />
                      <Route path="/attendance" element={<RoleRoute roles={['owner','admin','hr','department_manager']}><Attendance /></RoleRoute>} />
                        <Route path="/attendance-grid" element={<RoleRoute roles={['owner','admin','hr','department_manager']}><AttendanceGrid /></RoleRoute>} />
                        <Route path="/biometrics" element={<RoleRoute roles={['owner','admin','hr']}><Biometrics /></RoleRoute>} />
                      <Route path="/leave" element={<RoleRoute roles={['owner','admin','hr','department_manager']}><LeaveRequests /></RoleRoute>} />
                      <Route path="/leave-accrual" element={<RoleRoute roles={['owner','admin','hr']}><LeaveAccrual /></RoleRoute>} />
                      <Route path="/team" element={<RoleRoute roles={['owner','admin']}><Team /></RoleRoute>} />
                      <Route path="/request-tracking" element={<RequestTracking />} />
                      <Route path="/audit-logs" element={<RoleRoute roles={['owner','admin','hr','finance']}><AuditLogs /></RoleRoute>} />
                      <Route path="/billing" element={<RoleRoute roles={['owner','admin']}><Billing /></RoleRoute>} />
                      <Route path="/billing/success" element={<RoleRoute roles={['owner','admin']}><Billing /></RoleRoute>} />
                      <Route path="/company-settings" element={<RoleRoute roles={['owner','admin']}><CompanySettings /></RoleRoute>} />
                      <Route path="/integrations" element={<RoleRoute roles={['owner','admin','hr']}><Integrations /></RoleRoute>} />
                      <Route path="/compliance" element={<RoleRoute roles={['owner','admin','hr','department_manager']}><Compliance /></RoleRoute>} />
                      <Route path="/statutory-compliance" element={<RoleRoute roles={['owner','admin','finance','hr']}><StatutoryCompliance /></RoleRoute>} />
                      <Route path="/workflows" element={<RoleRoute roles={['owner','admin','hr']}><Workflows /></RoleRoute>} />
                      <Route path="/country-setup" element={<RoleRoute roles={['owner','admin','hr']}><RegionalOnboarding /></RoleRoute>} />
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
