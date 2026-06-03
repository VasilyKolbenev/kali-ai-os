import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppTheme {
  // Colors
  static const Color background = Color(0xFF08080B); // Refined Futurism: deeper near-black
  static const Color cardColor = Color(0x801A1A24); // Semi-transparent card (legacy)
  static const Color primary = Color(0xFF00D4FF); // Cyan accent (the one dominant accent)
  static const Color accent = Color(0xFFB400FF); // Purple — rare secondary micro-accent
  static const Color textPrimary = Colors.white;
  static const Color textSecondary = Color(0xFFA0A0AB);

  // Refined Futurism tokens (2026-06): frosted glass + hairline borders + dim text
  static const Color glassSurface = Color(0x0DFFFFFF); // white ~5% frosted fill
  static const Color glassBorder = Color(0x14FFFFFF); // white ~8% hairline
  static const Color textDim = Color(0x66FFFFFF); // white 40% — micro-labels

  // Gradients
  static const LinearGradient primaryGradient = LinearGradient(
    colors: [Color(0xFF00D4FF), Color(0xFFB400FF)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const LinearGradient subtleGradient = LinearGradient(
    colors: [Color(0x1A00D4FF), Color(0x1AB400FF)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static ThemeData get darkTheme {
    return ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: background,
      primaryColor: primary,
      colorScheme: const ColorScheme.dark(
        primary: primary,
        secondary: accent,
        surface: cardColor,
        background: background,
      ),
      textTheme: GoogleFonts.outfitTextTheme(ThemeData.dark().textTheme).copyWith(
        displayLarge: GoogleFonts.outfit(color: textPrimary, fontWeight: FontWeight.bold),
        displayMedium: GoogleFonts.outfit(color: textPrimary, fontWeight: FontWeight.bold),
        bodyLarge: GoogleFonts.inter(color: textPrimary),
        bodyMedium: GoogleFonts.inter(color: textSecondary),
      ),
      cardTheme: const CardThemeData(
        color: cardColor,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(20)),
          side: BorderSide(color: Color(0x0DFFFFFF), width: 1),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: cardColor,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: primary),
        ),
      ),
    );
  }
}
