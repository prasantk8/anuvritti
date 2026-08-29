/**
 * The Family's Own Language (PRD 40, PRD 56).
 *
 * No string is hardcoded in any screen. Every sentence respects the parent-child
 * relationship and the language actually spoken in the home.
 */

export interface StringCatalog {
  today: {
    emptyHeadline: string;
    emptyBody: string;
    sparkPrompt: string;
    rightNowPrompt: string;
    sayOutLoud: string;
    nothingHereYet: string;
    saved: string;
  };
  voice: {
    holdToRecord: string;
    recordingLive: string;
    savedNaturally: string;
    emptyVault: string;
    stillOnPhone: string;
    keptInFilm: string;
  };
  returns: {
    headline: string;
    savedTimeAgo: string;
    bringBackQuestion: string;
    optionLived: string;
    optionMaybeLater: string;
    optionNotAnymore: string;
    acknowledgedLived: string;
    acknowledgedLater: string;
    acknowledgedArchived: string;
  };
  pairing: {
    title: string;
    tagline: string;
    startFamily: string;
    joinWithCode: string;
    familyNameLabel: string;
    yourNameLabel: string;
    begin: string;
    codeLabel: string;
    join: string;
    pairingFailed: string;
    offline: string;
    timeout: string;
    conflict: string;
    generalError: string;
  };
  widgets: {
    rightNowTitle: string;
    tapToAnswer: string;
  };
  common: {
    cancel: string;
    save: string;
    delete: string;
    close: string;
  };
}

export type SupportedLocale = "en" | "hi" | "es" | "fr" | "de" | "ja";

export const EN_CATALOG: StringCatalog = {
  today: {
    emptyHeadline: "Nothing today.",
    emptyBody: "That is completely normal. The archive will be here when something happens.",
    sparkPrompt: "Notice something today",
    rightNowPrompt: "A quick question about right now",
    sayOutLoud: "Say something out loud →",
    nothingHereYet: "Nothing here yet. Share something to this app and it will be.",
    saved: "Saved.",
  },
  voice: {
    holdToRecord: "Hold to speak",
    recordingLive: "Listening",
    savedNaturally: "Saved to your archive",
    emptyVault: "Nothing yet. Say something to your child and keep it here.",
    stillOnPhone: "Still on your phone. It will go up when there's signal.",
    keptInFilm: "That's in this year's film.",
  },
  returns: {
    headline: "Something brought back for {childName}",
    savedTimeAgo: "You saved this {timeAgo}",
    bringBackQuestion: "{childName} may be ready now. What do you think?",
    optionLived: "We did it",
    optionMaybeLater: "Maybe later",
    optionNotAnymore: "Not relevant anymore",
    acknowledgedLived: "Noted as experienced together.",
    acknowledgedLater: "Resting for a quiet interval.",
    acknowledgedArchived: "Removed from future suggestions.",
  },
  pairing: {
    title: "Anuvritti",
    tagline: "For the little things you don't want life to erase.",
    startFamily: "Start our family",
    joinWithCode: "Join with a code",
    familyNameLabel: "What shall we call your family?",
    yourNameLabel: "And you?",
    begin: "Begin",
    codeLabel: "The code on the other phone",
    join: "Join",
    pairingFailed: "That code didn't work. Ask for a fresh one.",
    offline: "Can't reach home right now. Try again in a moment.",
    timeout: "That took too long. Try again?",
    conflict: "This server already belongs to a family.",
    generalError: "Something went wrong at our end.",
  },
  widgets: {
    rightNowTitle: "Right Now · {childName}",
    tapToAnswer: "Tap to note one sentence",
  },
  common: {
    cancel: "Cancel",
    save: "Save",
    delete: "Delete",
    close: "Close",
  },
};

export const HI_CATALOG: StringCatalog = {
  today: {
    emptyHeadline: "आज कुछ नहीं है।",
    emptyBody: "यह बिल्कुल स्वाभाविक है। जब भी कोई खास पल होगा, संग्रह यहीं रहेगा।",
    sparkPrompt: "आज कुछ नया महसूस किया",
    rightNowPrompt: "इस समय के बारे में एक छोटा सा सवाल",
    sayOutLoud: "कुछ बोलकर दर्ज करें →",
    nothingHereYet: "यहाँ अभी कुछ नहीं है। कुछ साझा करें और यह यहाँ दिखाई देगा।",
    saved: "सहेजा गया।",
  },
  voice: {
    holdToRecord: "बोलने के लिए दबाकर रखें",
    recordingLive: "रिकॉर्ड हो रहा है",
    savedNaturally: "संग्रह में सुरक्षित सहेजा गया",
    emptyVault: "अभी कुछ नहीं है। अपने बच्चे के लिए कुछ बोलें और यहाँ सहेजें।",
    stillOnPhone: "अभी आपके फ़ोन पर है। नेटवर्क मिलने पर सर्वर पर सुरक्षित हो जाएगा।",
    keptInFilm: "यह इस साल की फ़िल्म में शामिल है।",
  },
  returns: {
    headline: "{childName} के लिए एक पुरानी याद",
    savedTimeAgo: "आपने इसे {timeAgo} पहले सहेजा था",
    bringBackQuestion: "{childName} अब शायद इसके लिए तैयार हैं। आप क्या सोचते हैं?",
    optionLived: "हमने यह साथ किया",
    optionMaybeLater: "शायद बाद में",
    optionNotAnymore: "अब प्रासंगिक नहीं",
    acknowledgedLived: "साथ बिताए पल के रूप में दर्ज।",
    acknowledgedLater: "कुछ समय के लिए शांत अंतराल में।",
    acknowledgedArchived: "भविष्य के सुझावों से हटा दिया गया।",
  },
  pairing: {
    title: "अनुवृत्ति",
    tagline: "उन छोटे पलों के लिए जिन्हें आप खोना नहीं चाहते।",
    startFamily: "हमारा परिवार शुरू करें",
    joinWithCode: "कोड के साथ जुड़ें",
    familyNameLabel: "हम आपके परिवार को क्या नाम दें?",
    yourNameLabel: "और आपका नाम?",
    begin: "शुरू करें",
    codeLabel: "दूसरे फ़ोन पर दिख रहा कोड",
    join: "जुड़ें",
    pairingFailed: "वह कोड काम नहीं कर रहा। नया कोड मांगें।",
    offline: "अभी संपर्क नहीं हो पा रहा। कुछ देर बाद प्रयास करें।",
    timeout: "बहुत समय लग गया। दोबारा प्रयास करें?",
    conflict: "यह सर्वर पहले से एक परिवार से जुड़ा है।",
    generalError: "हमारी तरफ से कुछ गड़बड़ हुई।",
  },
  widgets: {
    rightNowTitle: "इस पल · {childName}",
    tapToAnswer: "एक वाक्य लिखने के लिए टैप करें",
  },
  common: {
    cancel: "रद्द करें",
    save: "सहेजें",
    delete: "हटाएं",
    close: "बंद करें",
  },
};

export const ES_CATALOG: StringCatalog = {
  today: {
    emptyHeadline: "Nada por hoy.",
    emptyBody: "Es completamente normal. El archivo estará aquí cuando suceda algo.",
    sparkPrompt: "Nota algo hoy",
    rightNowPrompt: "Una pregunta breve sobre este momento",
    sayOutLoud: "Di algo en voz alta →",
    nothingHereYet: "Nada por aquí todavía. Comparte algo y aparecerá aquí.",
    saved: "Guardado.",
  },
  voice: {
    holdToRecord: "Mantén presionado para hablar",
    recordingLive: "Escuchando",
    savedNaturally: "Guardado en tu archivo familiar",
    emptyVault: "Nada todavía. Di algo para tu hijo y guárdalo aquí.",
    stillOnPhone: "Aún en tu teléfono. Se subirá cuando haya señal.",
    keptInFilm: "Esto está en la película de este año.",
  },
  returns: {
    headline: "Un recuerdo para {childName}",
    savedTimeAgo: "Guardaste esto hace {timeAgo}",
    bringBackQuestion: "{childName} podría estar listo ahora. ¿Qué opinas?",
    optionLived: "Lo vivimos juntos",
    optionMaybeLater: "Tal vez después",
    optionNotAnymore: "Ya no es relevante",
    acknowledgedLived: "Registrado como vivido juntos.",
    acknowledgedLater: "En pausa por un tiempo tranquilo.",
    acknowledgedArchived: "Retirado de futuras sugerencias.",
  },
  pairing: {
    title: "Anuvritti",
    tagline: "Para las pequeñas cosas que la vida no debería borrar.",
    startFamily: "Comenzar nuestra familia",
    joinWithCode: "Unirse con un código",
    familyNameLabel: "¿Cómo llamaremos a tu familia?",
    yourNameLabel: "¿Y tú?",
    begin: "Comenzar",
    codeLabel: "El código en el otro teléfono",
    join: "Unirse",
    pairingFailed: "Ese código no funcionó. Solicita uno nuevo.",
    offline: "No se puede conectar ahora. Intenta de nuevo en un momento.",
    timeout: "Tardó demasiado. ¿Intentar de nuevo?",
    conflict: "Este servidor ya pertenece a una familia.",
    generalError: "Algo salió mal de nuestro lado.",
  },
  widgets: {
    rightNowTitle: "En este momento · {childName}",
    tapToAnswer: "Toca para escribir una frase",
  },
  common: {
    cancel: "Cancelar",
    save: "Guardar",
    delete: "Eliminar",
    close: "Cerrar",
  },
};

export const LOCALE_CATALOGS: Record<SupportedLocale, StringCatalog> = {
  en: EN_CATALOG,
  hi: HI_CATALOG,
  es: ES_CATALOG,
  fr: EN_CATALOG, // Fallback to base
  de: EN_CATALOG,
  ja: EN_CATALOG,
};
