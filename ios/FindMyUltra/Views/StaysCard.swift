import SwiftUI

/// „Wo war das Objekt wie lange?“ – Aufenthalte & häufige Orte.
struct StaysCard: View {
    @Environment(AppModel.self) private var model
    @State private var showAll = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Aufenthalte", systemImage: "mappin.and.ellipse").font(.headline)
                Spacer()
                Toggle("", isOn: Binding(get: { model.showStays }, set: { model.showStays = $0; Haptics.light() }))
                    .labelsHidden()
                    .tint(.yellow)
            }

            if model.stays.isEmpty {
                Text("Noch keine Aufenthalte in diesem Zeitraum. Ein Aufenthalt entsteht, wenn das Objekt mindestens \(Int(model.settings?.stays?.minMinutes ?? 5)) min im Umkreis von \(Int(model.settings?.stays?.radiusM ?? 120)) m geortet wurde.")
                    .font(.subheadline).foregroundStyle(.secondary)
            } else {
                HStack(spacing: 10) {
                    summary("\(model.stays.count)", "Aufenthalte")
                    summary("\(model.places.count)", "Orte")
                    summary(formatDuration(model.totalStayTime), "insgesamt")
                }

                if model.places.count > 1 {
                    Text("Häufigste Orte").font(.footnote.bold()).foregroundStyle(.secondary).padding(.top, 4)
                    ForEach(Array(model.places.prefix(4).enumerated()), id: \.element.id) { i, p in
                        PlaceRow(place: p, rank: i + 1)
                    }
                }

                Text("Verlauf").font(.footnote.bold()).foregroundStyle(.secondary).padding(.top, 4)
                let list = Array(model.stays.reversed())
                ForEach(showAll ? list : Array(list.prefix(8))) { st in
                    Button { model.select(stay: st) } label: {
                        StayRow(stay: st, selected: st.id == model.selectedStayID,
                                visits: model.places.first { $0.id == st.placeId }?.visits ?? 1)
                    }
                    .buttonStyle(PressableStyle())
                }
                if list.count > 8 && !showAll {
                    Button("Alle \(list.count) Aufenthalte anzeigen") { Haptics.light(); showAll = true }
                        .buttonStyle(.glass)
                }
            }
        }
        .padding(16)
        .background(Color(.secondarySystemGroupedBackground).opacity(0.7), in: .rect(cornerRadius: 22))
    }

    private func summary(_ v: String, _ l: String) -> some View {
        VStack(spacing: 2) {
            Text(v).font(.headline).lineLimit(1).minimumScaleFactor(0.7)
            Text(l).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(Color.yellow.opacity(0.14), in: .rect(cornerRadius: 14))
    }
}

struct StayRow: View {
    @Environment(AppModel.self) private var model
    let stay: Stay
    let selected: Bool
    let visits: Int
    @State private var address: String?

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                Circle().fill(Color.yellow.opacity(selected ? 1 : 0.85)).frame(width: 38, height: 38)
                Image(systemName: stay.ongoing ? "figure.stand" : "clock.fill")
                    .font(.system(size: 16, weight: .bold)).foregroundStyle(.black)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(address ?? String(format: "%.5f, %.5f", stay.lat, stay.lon))
                    .font(.subheadline.weight(.semibold)).foregroundStyle(.primary).lineLimit(2)
                    .multilineTextAlignment(.leading)
                Text(span).font(.caption).foregroundStyle(.secondary)
                HStack(spacing: 6) {
                    chip("\(stay.points) Berichte", .secondary)
                    if stay.outliers > 0 { chip("\(stay.outliers) Ausreißer ignoriert", .orange) }
                    if visits > 1 { chip("\(visits)× besucht", .blue) }
                }
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 3) {
                Text(formatDuration(stay.duration)).font(.headline.monospacedDigit()).foregroundStyle(.primary)
                if stay.ongoing {
                    Text("läuft noch").font(.caption.bold()).foregroundStyle(.green)
                } else {
                    Text("ca.").font(.caption2).foregroundStyle(.tertiary)
                }
            }
        }
        .padding(12)
        .background(selected ? Color.yellow.opacity(0.18) : Color(.tertiarySystemFill).opacity(0.5), in: .rect(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(selected ? Color.yellow : .clear, lineWidth: 1.5))
        .task(id: stay.id) { address = await model.address(lat: stay.lat, lon: stay.lon) }
    }

    private var span: String {
        let de = Locale(identifier: "de_DE")
        let s = stay.startDate, e = stay.endDate
        let day = s.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated).locale(de))
        let t1 = s.formatted(.dateTime.hour().minute().locale(de))
        let t2 = e.formatted(.dateTime.hour().minute().locale(de))
        let multi = !Calendar.current.isDate(s, inSameDayAs: e)
        return multi ? "\(day) \(t1) – \(e.formatted(.dateTime.weekday(.abbreviated).locale(de))) \(t2)"
                     : "\(day) · \(t1) – \(stay.ongoing ? "jetzt" : t2)"
    }

    private func chip(_ s: String, _ c: Color) -> some View {
        Text(s).font(.system(size: 10, weight: .semibold))
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(c.opacity(0.15), in: .capsule)
            .foregroundStyle(c == .secondary ? Color.secondary : c)
    }
}

struct PlaceRow: View {
    @Environment(AppModel.self) private var model
    let place: Place
    let rank: Int
    @State private var address: String?

    var body: some View {
        Button {
            Haptics.selection()
            model.show(center: place.coordinate, meters: max(400, place.radius * 6))
        } label: {
            HStack(spacing: 10) {
                Text("\(rank)").font(.caption.bold()).foregroundStyle(.black)
                    .frame(width: 22, height: 22).background(Color.yellow, in: .circle)
                Text(address ?? String(format: "%.4f, %.4f", place.lat, place.lon))
                    .font(.subheadline).lineLimit(1).foregroundStyle(.primary)
                Spacer()
                Text("\(place.visits)×").font(.caption).foregroundStyle(.secondary)
                Text(formatDuration(place.totalDuration)).font(.subheadline.weight(.semibold).monospacedDigit())
                    .foregroundStyle(.primary)
            }
        }
        .buttonStyle(.plain)
        .task(id: place.id) { address = await model.address(lat: place.lat, lon: place.lon) }
    }
}
