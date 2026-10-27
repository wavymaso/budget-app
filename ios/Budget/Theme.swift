import SwiftUI
import SwiftData

/// Budget's themes (Campo), the same as on the Mac (static/theme.js). Picking one here changes
/// the Mac too, and the other way round. A theme is a field colour (its own hue when you're on
/// plan; amber and red are the same in every theme) and the UI around it.
struct Theme: Equatable {
    let id: String
    let label: String
    let dark: Bool
    let background: Color
    let surface: Color
    let accent: Color
    let onAccent: Color
    let text: Color
    let secondary: Color
    let faint: Color
    let line: Color
    let fieldGreen: (Color, Color)        // the field and its deeper disc, by budget state
    let fieldAmber: (Color, Color)
    let fieldRed: (Color, Color)

    static func == (a: Theme, b: Theme) -> Bool { a.id == b.id }

    private static let lightNeutral = ["f4f4f5", "ececee", "e2e3e6", "cfd1d6", "a0a3ab", "70737b", "53565d", "3f4147", "27292d", "16171a", "0a0b0c"]
    private static let amber = (Color(hex: "a3600a"), Color(hex: "874f08")), red = (Color(hex: "b4272f"), Color(hex: "901c23"))

    private static func light(_ id: String, _ label: String, ground: String, field: String, deep: String) -> Theme {
        let n = [ground] + lightNeutral.dropFirst()
        return Theme(id: id, label: label, dark: false, background: Color(hex: n[0]), surface: .white, accent: Color(hex: field), onAccent: .white,
                     text: Color(hex: n[9]), secondary: Color(hex: n[5]), faint: Color(hex: n[4]), line: Color(hex: n[2]),
                     fieldGreen: (Color(hex: field), Color(hex: deep)), fieldAmber: amber, fieldRed: red)
    }

    static let all: [Theme] = [
        light("verde", "Verde", ground: "f1f4f2", field: "1d6a48", deep: "155238"),
        light("azul", "Azul", ground: "f1f3f8", field: "1f4fa8", deep: "173d84"),
        light("mar", "Mar", ground: "eff5f5", field: "0f6f70", deep: "0a5556"),
        light("ciruela", "Ciruela", ground: "f5f2f5", field: "6a2f6e", deep: "532456"),
        light("teja", "Teja", ground: "f6f2ef", field: "8a4b2c", deep: "6e3b22"),
        light("tinta", "Tinta", ground: "f3f3f4", field: "2a2b30", deep: "1a1b1f"),
        Theme(id: "noche", label: "Noche", dark: true, background: Color(hex: "0d0e10"), surface: Color(hex: "16171b"),
              accent: Color(hex: "5cc28f"), onAccent: Color(hex: "0d0e10"), text: Color(hex: "f3f4f6"), secondary: Color(hex: "868a93"),
              faint: Color(hex: "5c6068"), line: Color(hex: "27292e"),
              fieldGreen: (Color(hex: "15402d"), Color(hex: "0f3021")), fieldAmber: (Color(hex: "6b4109"), Color(hex: "573406")),
              fieldRed: (Color(hex: "6e1a20"), Color(hex: "581419"))),
    ]

    /// Themes from before the Campo look (Oct 2026) open as their nearest new one.
    static let old = ["light": "verde", "dark": "noche", "sand": "teja", "ocean": "mar", "lavender": "ciruela", "rose": "ciruela", "noir": "noche"]

    static func named(_ id: String, systemDark: Bool) -> Theme {
        let id = old[id] ?? id
        if id == "auto" { return systemDark ? all[6] : all[0] }
        return all.first { $0.id == id } ?? all[0]
    }

    /// The field's colour for a budget state (nil: no monthly budget, the theme's own colour).
    func field(_ s: BudgetState?) -> Color { (s == .amber ? fieldAmber : s == .red ? fieldRed : fieldGreen).0 }
    func fieldDeep(_ s: BudgetState?) -> Color { (s == .amber ? fieldAmber : s == .red ? fieldRed : fieldGreen).1 }

    /// Big numbers: a heavy grotesk, tight. (Sizes scale with Dynamic Type where they're used.)
    func display(_ size: CGFloat, _ weight: Font.Weight = .black) -> Font {
        .system(size: size, weight: weight, design: .default)
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
