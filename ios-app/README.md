# iOS app (SwiftUI)

Empty for now. The Xcode project will be added in Phase 2 (Semaine 6).

Planned layout:

```
ios-app/
  SkullTrading.xcodeproj
  SkullTrading/
    App/
      SkullTradingApp.swift
      AppEnvironment.swift
    Core/
      Networking/          API client (URLSession + Codable)
      Auth/                Supabase session, Sign in with Apple
      Storage/             Keychain wrappers
      Models/              Codable mirrors of vps2-api models
    Features/
      Onboarding/
      Dashboard/
      Signals/
      SignalDetail/
      TradeNow/            "Trader maintenant" sheet
      BinanceConnect/
      Positions/
      Profile/
      Paywall/
      Tools/               leverage calc, crypto score, backtest
    UI/
      DesignSystem.swift
      Components/
  SkullTradingTests/
  SkullTradingUITests/
```

Targets: iOS 17.0+. Build is done on a Mac with Xcode 15+ — this CI
environment cannot compile Swift.
