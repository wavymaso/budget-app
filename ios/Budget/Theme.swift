import SwiftUI
import SwiftData

/// Budget's themes, the same as on the Mac (static/theme.js). Picking one here
/// changes the Mac too, and the other way round.
struct Theme: Equatable {
    let id: String
    let label: String
    let dark: Bool
    let serif: Bool
    let background: Color
    let surface: Color
    let accent: Color
    let onAccent: Color
    let text: Color
    let secondary: Color
    let faint: Color
    let line: Color

    static func make(_ id: String, _ label: String, dark: Bool, serif: Bool, surface: String, accent: String, onAccent: String,
                     neutral: [String]) -> Theme {
        // neutral: 50..950, page background first (dark themes run the other way)
        Theme(id: id, label: label, dark: dark, serif: serif, background: Color(hex: neutral[0]), surface: Color(hex: surface),
              accent: Color(hex: accent), onAccent: Color(hex: onAccent), text: Color(hex: neutral[9]),
              secondary: Color(hex: neutral[5]), faint: Color(hex: neutral[4]), line: Color(hex: neutral[2]))
    }

    static let all: [Theme] = [
        make("light", "Light", dark: false, serif: false, surface: "ffffff", accent: "18181b", onAccent: "ffffff",
             neutral: ["f7f7f8", "f0f0f2", "e4e4e7", "d4d4d8", "a1a1aa", "71717a", "52525b", "3f3f46", "27272a", "18181b", "09090b"]),
        make("dark", "Dark", dark: true, serif: false, surface: "17191f", accent: "b7c4ff", onAccent: "0d0e12",
             neutral: ["0d0e12", "20232b", "2b2f39", "3c414d", "697084", "8f96a8", "b1b7c6", "cdd2dd", "e3e6ed", "f3f4f8", "ffffff"]),
        make("sand", "Sand", dark: false, serif: true, surface: "fffdf8", accent: "9a4a2c", onAccent: "fffaf3",
             neutral: ["f4eee4", "efe7da", "e4d9c8", "d3c4ae", "a69680", "7a6b58", "5a4e40", "463c31", "2d261f", "1f1a15", "110e0b"]),
        make("ocean", "Ocean", dark: false, serif: false, surface: "ffffff", accent: "1d5a7d", onAccent: "ffffff",
             neutral: ["edf2f5", "e3eaef", "d2dde5", "b5c6d2", "8399a8", "5c7282", "425664", "324350", "1f2c36", "121d25", "080f14"]),
        make("lavender", "Lavender", dark: false, serif: false, surface: "ffffff", accent: "6a4c9c", onAccent: "ffffff",
             neutral: ["f4f2f8", "edeaf4", "e0dbeb", "cbc4da", "9d94b1", "726a86", "554e66", "413b4f", "2a2634", "1b1822", "0e0c12"]),
        make("rose", "Rose", dark: false, serif: true, surface: "fffbfa", accent: "8e2c48", onAccent: "fff7f8",
             neutral: ["f8efee", "f3e6e5", "eadad8", "dbc5c3", "b09897", "84706f", "634f50", "4d3c3d", "322627", "211819", "120c0d"]),
        make("noir", "Noir", dark: true, serif: true, surface: "121212", accent: "d8b46a", onAccent: "141008",
             neutral: ["050505", "1c1c1c", "262626", "363636", "5e5e5e", "8a8a8a", "ababab", "c8c8c8", "e0e0e0", "f2f2f2", "ffffff"]),
    ]

    static func named(_ id: String, systemDark: Bool) -> Theme {
        if id == "auto" { return all[systemDark ? 1 : 0] }
        return all.first { $0.id == id } ?? all[0]
    }

    func display(_ size: CGFloat, _ weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: serif ? .serif : .rounded)
    }

    func levelColor(_ l: Level?) -> Color {
        switch l {
        case .red: return Color(hex: dark ? "f87171" : "dc2626")
        case .amber: return Color(hex: dark ? "fbbf24" : "d97706")
        case .green: return Color(hex: dark ? "34d399" : "059669")
        case nil: return accent
        }
    }
}

private struct ThemeKey: EnvironmentKey { static let defaultValue = Theme.all[0] }
extension EnvironmentValues {
    var theme: Theme {
        get { self[ThemeKey.self] }
        set { self[ThemeKey.self] = newValue }
    }
}

extension Color {
    init(hex: String) {
        let h = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        var v: UInt64 = 0
        Scanner(string: h.count == 3 ? h.map { "\($0)\($0)" }.joined() : h).scanHexInt64(&v)
        self.init(red: Double((v >> 16) & 0xff) / 255, green: Double((v >> 8) & 0xff) / 255, blue: Double(v & 0xff) / 255)
    }
}

/// A rounded card, like the Mac app's.
struct Card<Content: View>: View {
    @Environment(\.theme) private var theme
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 0) { content }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(theme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).stroke(theme.line.opacity(0.6), lineWidth: 0.5))
            .shadow(color: .black.opacity(theme.dark ? 0 : 0.05), radius: 14, y: 6)
    }
}
