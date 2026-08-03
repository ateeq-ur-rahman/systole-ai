import {
  FileText, Image as ImageIcon, Video, Archive, Package,
  FileSpreadsheet, Presentation, File as FileGeneric, type LucideIcon,
} from "lucide-react";
import { categoryOf } from "../utils/format";

const ICONS: Record<string, LucideIcon> = {
  pdf: FileText,
  document: FileText,
  spreadsheet: FileSpreadsheet,
  presentation: Presentation,
  image: ImageIcon,
  video: Video,
  archive: Archive,
  installer: Package,
  file: FileGeneric,
};

export function FileIcon({ filename, size = 18 }: { filename: string; size?: number }) {
  const category = categoryOf(filename);
  const Icon = ICONS[category] ?? FileGeneric;
  return (
    <div className="file-icon">
      <Icon size={size} strokeWidth={2} />
    </div>
  );
}
