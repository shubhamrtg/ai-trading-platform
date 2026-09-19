const statusColors: Record<string, string> = {
  COMPLETED: 'bg-green-100 text-green-800',
  ACTIVE: 'bg-green-100 text-green-800',
  RUNNING: 'bg-blue-100 text-blue-800',
  CREATED: 'bg-gray-100 text-gray-800',
  DRAFT: 'bg-gray-100 text-gray-800',
  FAILED: 'bg-red-100 text-red-800',
  DISABLED: 'bg-red-100 text-red-800',
  DEPRECATED: 'bg-yellow-100 text-yellow-800',
  REJECTED: 'bg-red-100 text-red-800',
};

export default function StatusBadge({ status }: { status: string }) {
  const colorClass = statusColors[status] || 'bg-gray-100 text-gray-800';
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colorClass}`}
    >
      {status}
    </span>
  );
}
