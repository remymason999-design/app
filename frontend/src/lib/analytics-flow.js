export async function afterSuccessfulMutation(mutation, onSuccess) {
    const result = await mutation();
    onSuccess(result);
    return result;
}

export function captureLogoutAndReset(analyticsClient, user) {
    analyticsClient.capture(analyticsClient.EVENTS.LOGOUT, {}, { user, allowDuplicate: true });
    analyticsClient.reset();
}

export async function deleteAccountWithAnalytics(mutation, analyticsClient, user, logout) {
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