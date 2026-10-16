package app.piko.android.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/** "Tactile Clay Safety" palette from screens/tactile_clay_safety/DESIGN.md. */
object Clay {
    val Canvas = Color(0xFFF5F2EA)
    val Surface = Color(0xFFFAF8F4)
    val Well = Color(0xFFF0EDE4)
    val Primary = Color(0xFF8273C8)
    val PrimaryDeep = Color(0xFF5E4FA2)
    val SoftLavender = Color(0xFFDCD5F5)
    val Sky = Color(0xFFD8E9F5)
    val Mint = Color(0xFFD4EBDD)
    val ForestMint = Color(0xFF33845C)
    val Peach = Color(0xFFF5D8C9)

    // Opaque blends over the card surface: translucent tints let the card shadow show through as a box.
    val PeachSoft = Color(0xFFF8E8DE)
    val LavenderSoft = Color(0xFFEBE6F5)
    val Text = Color(0xFF29283A)
    val TextSecondary = Color(0xFF777588)
    val Caution = Color(0xFFB87A2C)

    /** Reserved by the design for SOS and acute distress. Used here only for hard failures. */
    val Critical = Color(0xFFC83F4D)
    val CriticalSoft = Color(0xFFFFDAD6)
}

private val scheme: ColorScheme = lightColorScheme(
    primary = Clay.PrimaryDeep,
    onPrimary = Color.White,
    primaryContainer = Clay.SoftLavender,
    onPrimaryContainer = Clay.Text,
    secondary = Clay.ForestMint,
    secondaryContainer = Clay.Mint,
    background = Clay.Canvas,
    onBackground = Clay.Text,
    surface = Clay.Surface,
    onSurface = Clay.Text,
    onSurfaceVariant = Clay.TextSecondary,
    error = Clay.Critical,
    errorContainer = Clay.CriticalSoft,
)

@Composable
fun PikoTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = scheme, content = content)
}

@Composable
fun ClayCard(modifier: Modifier = Modifier, tint: Color = Clay.Surface, content: @Composable () -> Unit) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(26.dp),
        color = tint,
        shadowElevation = 6.dp,
        tonalElevation = 0.dp,
    ) {
        Box(Modifier.padding(20.dp)) { content() }
    }
}

@Composable
fun ClayButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    soft: Boolean = false,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.fillMaxWidth().height(56.dp),
        shape = RoundedCornerShape(percent = 50),
        colors = if (soft) {
            ButtonDefaults.buttonColors(containerColor = Clay.SoftLavender, contentColor = Clay.Text)
        } else {
            ButtonDefaults.buttonColors(containerColor = Clay.PrimaryDeep, contentColor = Color.White)
        },
        elevation = ButtonDefaults.buttonElevation(defaultElevation = 6.dp, pressedElevation = 1.dp),
    ) {
        Text(text, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
fun Chip(text: String, background: Color, contentColor: Color = Clay.Text, modifier: Modifier = Modifier) {
    Surface(modifier = modifier, shape = RoundedCornerShape(percent = 50), color = background, contentColor = contentColor) {
        Text(
            text,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
fun Label(text: String) {
    Text(text.uppercase(), style = MaterialTheme.typography.labelSmall, color = Clay.PrimaryDeep, fontWeight = FontWeight.SemiBold)
}

@Composable
fun StatRow(left: String, right: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(left, style = MaterialTheme.typography.bodyMedium, color = Clay.TextSecondary)
        Text(right, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
fun VGap(dp: Int = 12) = Spacer(Modifier.height(dp.dp))

