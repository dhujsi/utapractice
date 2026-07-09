package com.utapractice.app;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.util.Base64;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

public class LocalAudioProvider extends ContentProvider {
    public static final String AUTHORITY = "com.utapractice.app.audio";

    public static Uri audioUri(Context context, String songName) {
        String safeName = safeName(songName);
        File audio = audioFile(context, safeName);
        return new Uri.Builder()
            .scheme("content")
            .authority(AUTHORITY)
            .appendPath("audio")
            .appendPath(safeName)
            .appendQueryParameter("v", String.valueOf(audio.lastModified()))
            .appendQueryParameter("size", String.valueOf(audio.length()))
            .build();
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public String getType(Uri uri) {
        String safeName = safeNameFromUri(uri);
        if (safeName.isEmpty()) return "audio/mpeg";
        return audioMimeFile(safeName);
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (mode != null && !mode.equals("r")) throw new FileNotFoundException("Local audio is read-only");
        String safeName = safeNameFromUri(uri);
        if (safeName.isEmpty()) throw new FileNotFoundException("Missing local audio name");
        File audio = audioFile(providerContext(), safeName);
        if (!audio.exists() || audio.length() <= 0) throw new FileNotFoundException("Local audio not found");
        return ParcelFileDescriptor.open(audio, ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder) {
        return null;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }

    private Context providerContext() throws FileNotFoundException {
        Context context = getContext();
        if (context == null) throw new FileNotFoundException("Context unavailable");
        return context;
    }

    private String safeNameFromUri(Uri uri) {
        if (uri == null || uri.getPathSegments().size() < 2) return "";
        if (!"audio".equals(uri.getPathSegments().get(0))) return "";
        return uri.getPathSegments().get(1);
    }

    private static File cacheDir(Context context, String name) {
        return new File(context.getFilesDir(), name);
    }

    private static File audioFile(Context context, String safeName) {
        return new File(cacheDir(context, "audio"), safeName + ".bin");
    }

    private File audioMimeSidecar(String safeName) throws FileNotFoundException {
        return new File(cacheDir(providerContext(), "audio"), safeName + ".mime");
    }

    private String audioMimeFile(String safeName) {
        try (InputStream input = new FileInputStream(audioMimeSidecar(safeName))) {
            String mime = new String(readAll(input), StandardCharsets.UTF_8).trim();
            return mime.isEmpty() ? "audio/mpeg" : mime;
        } catch (IOException error) {
            return "audio/mpeg";
        }
    }

    private byte[] readAll(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        return output.toByteArray();
    }

    private static String safeName(String value) {
        return Base64.encodeToString(value.getBytes(StandardCharsets.UTF_8), Base64.URL_SAFE | Base64.NO_WRAP);
    }
}
