//! Тесты debug-only рычага `KALI_BOOT_DELAY_MS`.
//!
//! Вынесены в отдельный модуль под `#[cfg(debug_assertions)]`: рычаг
//! (`parse_boot_delay_ms`/`gate_owned_healthy`/`DelayedProbe`) отсутствует в
//! release-сборке, поэтому и его тесты не должны компилироваться там —
//! иначе `cargo test --release` падал бы на несуществующих элементах.
//!
//! A3 acceptance (owner): рычаг задерживает ТОЛЬКО признание готовности, без
//! sleep (неблокирующая проверка дедлайна), не маскирует Foreign/реальные
//! ошибки и не убивает живой child.
use super::*;

#[test]
fn boot_delay_parse_rejects_invalid_and_clamps() {
    // валидное значение проходит как есть
    assert_eq!(parse_boot_delay_ms(Some("45000")), 45_000);
    assert_eq!(parse_boot_delay_ms(Some("  45000  ")), 45_000); // обрезка пробелов
    assert_eq!(parse_boot_delay_ms(Some("0")), 0);
    // любое некорректное → 0 (рычаг выключен), никогда не паника
    for bad in ["", "   ", "abc", "-5", "-1", "4.5", "1e3", "45000ms"] {
        assert_eq!(parse_boot_delay_ms(Some(bad)), 0, "bad input: {bad:?}");
    }
    // переполнение u64 → 0, а не wrap
    assert_eq!(parse_boot_delay_ms(Some("999999999999999999999999")), 0);
    // отсутствие переменной → 0
    assert_eq!(parse_boot_delay_ms(None), 0);
    // чрезмерное значение зажимается разумной верхней границей
    assert_eq!(parse_boot_delay_ms(Some("99999999")), MAX_BOOT_DELAY_MS);
}

#[test]
fn boot_delay_gate_holds_owned_healthy_until_deadline() {
    let delay = Duration::from_millis(45_000);
    // до дедлайна OwnedHealthy подменяется на Unhealthy
    for before in [0u64, 1, 44_999] {
        assert_eq!(
            gate_owned_healthy(
                ProbeStatus::OwnedHealthy,
                Duration::from_millis(before),
                delay
            ),
            ProbeStatus::Unhealthy,
            "elapsed={before}"
        );
    }
    // на дедлайне и после — настоящий OwnedHealthy
    for after in [45_000u64, 45_001, 90_000] {
        assert_eq!(
            gate_owned_healthy(
                ProbeStatus::OwnedHealthy,
                Duration::from_millis(after),
                delay
            ),
            ProbeStatus::OwnedHealthy,
            "elapsed={after}"
        );
    }
    // delay=0 (рычаг выключен) — не влияет никогда
    assert_eq!(
        gate_owned_healthy(ProbeStatus::OwnedHealthy, Duration::ZERO, Duration::ZERO),
        ProbeStatus::OwnedHealthy
    );
}

#[test]
fn boot_delay_gate_never_masks_foreign_or_unhealthy() {
    let delay = Duration::from_millis(45_000);
    for elapsed in [Duration::ZERO, Duration::from_millis(90_000)] {
        // чужой бэкенд обязан остаться Foreign — иначе рычаг спрятал бы реальную проблему
        assert_eq!(
            gate_owned_healthy(ProbeStatus::ForeignHealthy, elapsed, delay),
            ProbeStatus::ForeignHealthy
        );
        // реальная неготовность остаётся неготовностью
        assert_eq!(
            gate_owned_healthy(ProbeStatus::Unhealthy, elapsed, delay),
            ProbeStatus::Unhealthy
        );
    }
}

#[test]
fn supervise_boot_delay_holds_python_starting_then_ready() {
    let inner = FakeProbe::new(false, Some("id-1"));
    let mut spawner = FakeSpawner::new(-1);
    let clk = clock();
    let t0 = clk.now();
    let mut ctx = SuperviseCtx::new(true);
    ctx.rust_bound = Some(BindOutcome::Ok);
    let mut emits = Vec::new();
    let never = AtomicBool::new(false);

    let probe = DelayedProbe::new(inner, &clk, t0, 45_000);

    // RustReady + spawn → PythonStarting
    for _ in 0..2 {
        supervise_step(&mut ctx, &probe, &mut spawner, &clk, &never, &mut |s| {
            emits.push(s)
        });
        clk.advance(Duration::from_millis(500));
    }
    probe.inner_ref().up.set(true); // backend реально поднялся, ID совпадает

    // до дедлайна: держим PythonStarting, живой child НЕ убит, повторно не спавним
    for _ in 0..10 {
        supervise_step(&mut ctx, &probe, &mut spawner, &clk, &never, &mut |s| {
            emits.push(s)
        });
        clk.advance(Duration::from_millis(1_000));
    }
    assert_eq!(ctx.state, StartupState::PythonStarting, "рычаг держит boot");
    assert!(
        !spawner.last_terminated.get(),
        "живой child не убит рычагом"
    );
    assert_eq!(spawner.count, 1, "повторного spawn нет");

    // перешагиваем дедлайн → PythonReady
    clk.advance(Duration::from_millis(45_000));
    supervise_step(&mut ctx, &probe, &mut spawner, &clk, &never, &mut |s| {
        emits.push(s)
    });
    assert_eq!(
        ctx.state,
        StartupState::PythonReady,
        "после дедлайна — готов"
    );
    assert_eq!(spawner.count, 1, "spawn по-прежнему ровно один");
    assert_eq!(
        emits,
        vec![
            StartupState::RustReady,
            StartupState::PythonStarting,
            StartupState::PythonReady
        ],
        "ровно один переход в каждое состояние (level-triggered)"
    );
}
