export default function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="text-center py-12">
      <div className="text-red-500 text-4xl mb-4">⚠</div>
      <h3 className="text-lg font-medium text-gray-900">{title}</h3>
      {message && <p className="mt-2 text-sm text-red-600">{message}</p>}
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          Try Again
        </button>
      )}
    </div>
  );
}
