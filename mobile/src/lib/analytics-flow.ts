export async function afterSuccessfulMutation<T>(
  mutation: () => Promise<T>,
  onSuccess: (result: T) => void
): Promise<T> {
  const result = await mutation();
  onSuccess(result);
  return result;
}

type LogoutAnalyticsClient<User> = {
  EVENTS: { LOGOUT: string };
  capture: (event: string, props: Record<string, unknown>, options: { user: User; allowDuplicate: boolean }) => void;
  reset: () => void;
};

export function captureLogoutAndReset<User>(
  analyticsClient: LogoutAnalyticsClient<User>,
  user: User
): void {
  analyticsClient.capture(analyticsClient.EVENTS.LOGOUT, {}, { user, allowDuplicate: true });
  analyticsClient.reset();
}

type DeletionAnalyticsClient<User> = LogoutAnalyticsClient<User> & {
  EVENTS: { LOGOUT: string; ACCOUNT_DELETED: string };
};

export async function deleteAccountWithAnalytics<User>(
  mutation: () => Promise<unknown>,
  analyticsClient: DeletionAnalyticsClient<User>,
  user: User,
  logout: () => Promise<void>
): Promise<void> {
  await afterSuccessfulMutation(
    mutation,
    () => analyticsClient.capture(
      analyticsClient.EVENTS.ACCOUNT_DELETED,
      {},
      { user, allowDuplicate: true }
    )
  );
  await logout();
}