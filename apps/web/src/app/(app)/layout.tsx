import { AppShell } from "@/components/app-shell";

export default function AuthenticatedLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
