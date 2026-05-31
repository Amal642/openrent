import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "@/api/client";

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

export function useApiMutation<TData, TVariables>({
  mutationFn,
  success,
  error,
  invalidate = [],
}: {
  mutationFn: (variables: TVariables) => Promise<TData>;
  success: string;
  error: string;
  invalidate?: QueryKey[];
}) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      invalidate.forEach((queryKey) => queryClient.invalidateQueries({ queryKey }));
      toast.success(success);
    },
    onError: (err) => toast.error(errorMessage(err, error)),
  });
}
