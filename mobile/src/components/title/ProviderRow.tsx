import { StyleSheet, Text, View } from "react-native";

import { ProviderLogo } from "@/components/ProviderLogo";
import { Colors } from "@/constants/colors";
import type { StreamingService } from "@/lib/content-api";
import { providerDisplayName } from "@/lib/providers";

interface Props {
  serviceId: string;
  service?: StreamingService;
  /** "Included with your plan" styling when the user is subscribed. */
  included?: boolean;
}

/**
 * A single streaming provider row — "Included with X" style, mirroring the
 * web app's ProviderRow. Falls back to an initial when no logo is available.
 */
export function ProviderRow({ serviceId, service, included }: Props) {
  const name = providerDisplayName(serviceId, service?.name);

  return (
    <View style={styles.row} accessible accessibilityLabel={`${included ? "Included with" : "Available on"} ${name}`}>
      <ProviderLogo
        sid={serviceId}
        name={service?.name}
        logoUrl={service?.logo_path}
        size={44}
        radius={12}
      />
      <View style={styles.textWrap}>
        <Text style={styles.included} numberOfLines={1}>
          {included ? "Included with" : "Available on"}
        </Text>
        <Text style={styles.name} numberOfLines={1}>
          {name}
        </Text>
      </View>
      {included ? (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>Your plan</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: Colors.surface,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  textWrap: { flex: 1 },
  included: {
    fontFamily: "Inter_500Medium",
    fontSize: 11,
    color: Colors.textTertiary,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  name: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text, marginTop: 1 },
  badge: {
    backgroundColor: "rgba(34,197,94,0.14)",
    borderColor: "rgba(34,197,94,0.35)",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  badgeText: { fontFamily: "Inter_600SemiBold", fontSize: 10, color: Colors.success },
});
